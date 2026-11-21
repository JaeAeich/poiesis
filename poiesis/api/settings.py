"""API-side settings derived from environment variables.

Single place that reads env. Held in a Pydantic settings object so the
TaskPod RuntimeConfig and the database DSN come from one validated source.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx
from kubernetes.client import (
    V1EnvVar,
    V1EnvVarSource,
    V1ResourceRequirements,
    V1SecretKeySelector,
)
from kubernetes.utils import parse_quantity  # ty: ignore[unresolved-import]
from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.core.constants import FILE_URL_ROOTS_ENV, OUTPUT_GLOB_FALLBACK_ENV
from poiesis.core.services.filer.file_urls import parse_file_url_roots
from poiesis.core.taskpod import PodSecurityEnforce, RuntimeConfig

if TYPE_CHECKING:
    from decimal import Decimal

logger = logging.getLogger(__name__)

#: Resources of trec, of tif and tof, and of ack, as JSON resources blocks.
RECORDER_RESOURCES_ENV = "POIESIS_TASKPOD_RECORDER_RESOURCES"
FILER_RESOURCES_ENV = "POIESIS_TASKPOD_FILER_RESOURCES"
ACK_RESOURCES_ENV = "POIESIS_TASKPOD_ACK_RESOURCES"


def _parse_int_env(name: str, default: int | None = None) -> int | None:
    """Parse an int from env; empty/unset returns default; bad value raises."""
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _parse_seconds_env(name: str, default: float) -> float:
    """Parse a positive, finite number of seconds; empty/unset is default."""
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    message = f"{name} must be a positive number of seconds, got {raw!r}"
    try:
        seconds = float(raw)
    except ValueError as exc:
        raise ValueError(message) from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(message)
    return seconds


def _parse_optional_int_env(name: str) -> int | None:
    """Like _parse_int_env but returns None on empty AND on literal 'null'.

    Used for ``retain_after_seconds`` and ``max_disk_size_gi`` where the
    chart's ``null`` sentinel must reach the runtime as ``None``.
    """
    raw = os.environ.get(name, "")
    if raw == "" or raw.lower() in {"null", "none"}:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer or unset, got {raw!r}") from exc


def _parse_time_limit_env(name: str, default: int) -> int | None:
    """Parse a task time limit: whole seconds >= 1, or 'null' for no limit.

    Unset/empty is default. Anything else raises, so a typo stops the API
    at startup instead of silently changing how long tasks may run.
    """
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    if raw.lower() in {"null", "none"}:
        return None
    message = f"{name} must be an integer >= 1 or null, got {raw!r}"
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise ValueError(message) from exc
    if seconds < 1:
        raise ValueError(message)
    return seconds


def _parse_csv_env(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Comma-separated env value → tuple. Empty/unset returns default."""
    raw = os.environ.get(name, "")
    parts = tuple(s.strip() for s in raw.split(",") if s.strip())
    return parts or default


def _parse_json_object_env(name: str) -> dict[str, str]:
    """JSON-object env value → dict[str, str]. Empty/unset returns {}.

    Invalid JSON or non-object payloads log a warning and return {} so a
    malformed chart input degrades visibly rather than crashing startup.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("%s is not valid JSON; ignoring", name)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("%s must encode a JSON object; ignoring", name)
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


def _parse_json_strings_env(name: str) -> tuple[str, ...]:
    """JSON-array-of-strings env value → tuple. Empty/unset returns ().

    JSON rather than CSV because values such as group URNs may contain
    commas. Anything but an array of strings raises.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list) or not all(isinstance(v, str) for v in parsed):
        raise TypeError(f"{name} must encode a JSON array of strings")
    return tuple(parsed)


def _parse_json_array_env(name: str) -> list[dict[str, Any]]:
    """JSON-array-of-objects env value → list[dict].

    Empty/unset returns []. Invalid JSON or wrong shape raises so a
    misconfigured chart fails the api pod startup with a clear message.
    Used for operator-supplied taskpod extras (env / volumes /
    volume_mounts) where silently dropping a malformed entry would be
    worse than a loud failure.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise TypeError(f"{name} must encode a JSON array")
    items: list[dict[str, Any]] = []
    for idx, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise TypeError(f"{name}[{idx}] must be a JSON object")
        items.append({str(k): v for k, v in entry.items()})
    return items


def _parse_quantity(where: str, quantity: object) -> Decimal:
    """A non-negative Kubernetes quantity (``100m``, ``256Mi``, ``2``)."""
    if isinstance(quantity, bool) or not isinstance(quantity, (str, int, float)):
        raise TypeError(f"{where} must be a quantity, got {quantity!r}")
    try:
        amount = parse_quantity(quantity)
    except ValueError as exc:
        raise ValueError(f"{where} is not a quantity: {quantity!r}") from exc
    if amount < 0:
        raise ValueError(f"{where} must not be negative, got {quantity!r}")
    return amount


def _parse_resources_env(name: str) -> dict[str, dict[str, str]] | None:
    """JSON Kubernetes resources block env value → {requests, limits}.

    Empty/unset returns None: the container gets no requests or limits.
    Anything else must be an object with only ``requests`` and ``limits``,
    each mapping resource names to non-negative quantities (``100m``,
    ``256Mi``), with no request above its limit. A bad value raises, so
    the API stops at startup rather than every TaskPod being rejected.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TypeError(f"{name} must encode a JSON object")
    unknown = set(parsed) - {"requests", "limits"}
    if unknown:
        raise ValueError(f"{name}: unknown keys {sorted(unknown)}")
    block: dict[str, dict[str, str]] = {}
    amounts: dict[str, dict[str, Decimal]] = {"requests": {}, "limits": {}}
    for kind in ("requests", "limits"):
        entries = parsed.get(kind)
        if entries is None:
            continue
        if not isinstance(entries, dict):
            raise TypeError(f"{name}.{kind} must be a JSON object")
        block[kind] = {}
        for resource, quantity in entries.items():
            where = f"{name}.{kind}.{resource}"
            amounts[kind][resource] = _parse_quantity(where, quantity)
            block[kind][resource] = str(quantity)
    _check_requests_within_limits(name, amounts)
    return block or None


def _check_requests_within_limits(
    name: str, amounts: dict[str, dict[str, Decimal]]
) -> None:
    """Refuse a request above its limit: Kubernetes rejects such a Pod."""
    for resource, request in amounts["requests"].items():
        limit = amounts["limits"].get(resource)
        if limit is not None and request > limit:
            raise ValueError(f"{name}: requests.{resource} is above limits.{resource}")


def _resources(
    block: dict[str, dict[str, str]] | None,
) -> V1ResourceRequirements | None:
    """Parsed resources block → the container's V1ResourceRequirements."""
    if block is None:
        return None
    return V1ResourceRequirements(
        requests=block.get("requests"), limits=block.get("limits")
    )


#: Env-var names operators cannot redefine via ``taskpods.extraEnv``.
#: Collisions are rejected at Settings construction so the API pod fails
#: to start with a clear message rather than producing duplicate-env
#: rejection at every task submit.
_RESERVED_ENV_NAMES: frozenset[str] = frozenset(
    {
        "DATABASE_URL",
        "AWS_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "POIESIS_POD_NAME",
        "POIESIS_POD_NAMESPACE",
    }
)
_RESERVED_ENV_PREFIXES: tuple[str, ...] = ("POIESIS_",)

#: Volume names the chart already uses; operator extras cannot reuse these.
_RESERVED_VOLUME_NAMES: frozenset[str] = frozenset({"task-data", "postgres-ca", "tmp"})


def _check_reserved_env(entries: list[dict[str, Any]]) -> None:
    """Reject operator-supplied env that clashes with chart-internal names."""
    for idx, entry in enumerate(entries):
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"POIESIS_TASKPOD_EXTRA_ENV[{idx}] missing required 'name'"
            )
        if name in _RESERVED_ENV_NAMES or any(
            name.startswith(p) for p in _RESERVED_ENV_PREFIXES
        ):
            raise ValueError(
                f"POIESIS_TASKPOD_EXTRA_ENV[{idx}].name={name!r} collides with a "
                "chart-internal env var; pick a different name"
            )


def _check_reserved_volume(entries: list[dict[str, Any]], setting_name: str) -> None:
    """Reject operator-supplied volume/mount entries with reserved names."""
    for idx, entry in enumerate(entries):
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"{setting_name}[{idx}] missing required 'name'")
        if name in _RESERVED_VOLUME_NAMES:
            raise ValueError(
                f"{setting_name}[{idx}].name={name!r} is reserved by the chart"
            )


def _parse_and_check_env_extras() -> list[dict[str, Any]]:
    """Parse POIESIS_TASKPOD_EXTRA_ENV and reject reserved-name collisions."""
    entries = _parse_json_array_env("POIESIS_TASKPOD_EXTRA_ENV")
    _check_reserved_env(entries)
    return entries


def _parse_and_check_volume_extras(name: str) -> list[dict[str, Any]]:
    """Parse a volume/mount extras env and reject reserved-name collisions."""
    entries = _parse_json_array_env(name)
    _check_reserved_volume(entries, name)
    return entries


def _entries_to_envvars(entries: list[dict[str, Any]]) -> list[V1EnvVar]:
    """Convert JSON-shaped env entries to V1EnvVar instances.

    Supports the two common shapes:
    {"name": "X", "value": "1"}
    {"name": "X", "valueFrom": {"secretKeyRef": {...}}}
    """
    out: list[V1EnvVar] = []
    for entry in entries:
        name = entry["name"]
        if "value" in entry:
            out.append(V1EnvVar(name=name, value=str(entry["value"])))
        elif "valueFrom" in entry or "value_from" in entry:
            out.append(
                V1EnvVar(
                    name=name,
                    value_from=entry.get("valueFrom") or entry.get("value_from"),
                )
            )  # type: ignore[arg-type]
        else:
            out.append(V1EnvVar(name=name))
    return out


def _secret_env(
    name: str, secret: str, key: str, *, optional: bool = False
) -> V1EnvVar:
    """Env var read from a Secret key in the TaskPod's namespace."""
    return V1EnvVar(
        name=name,
        value_from=V1EnvVarSource(
            secret_key_ref=V1SecretKeySelector(
                name=secret, key=key, optional=True if optional else None
            )
        ),
    )


DEFAULT_POIESIS_IMAGE = "docker.io/jaeaeich/poiesis:latest"


_ISSUERS_ENV = "POIESIS_AUTH_ISSUERS"
_REMOVED_ENV_PREFIX = "POIESIS_AUTH_OIDC_"
_REMOVED_CLAIM_ENV_PREFIX = "POIESIS_AUTHZ_REQUIRED_CLAIM_"


def _refuse_removed_env(prefix: str, replacement: str) -> None:
    """Refuse to start while a variable named ``prefix*`` is set.

    For settings that were replaced: silently ignoring a leftover one
    would run with settings the operator didn't intend.
    """
    removed = sorted(n for n in os.environ if n.startswith(prefix))
    if removed:
        raise ValueError(
            ", ".join(removed) + f" is no longer read: {prefix}* was "
            f"replaced by {replacement}"
        )


def _is_http_url(value: str) -> bool:
    """Whether ``value`` is an absolute http(s) URL with a host."""
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        return False
    return url.scheme in {"http", "https"} and bool(url.host)


class UserinfoSettings(BaseModel):
    """Per-issuer userinfo lookup (see `poiesis.api.jwt_auth`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Fetch the issuer's userinfo per token (cached) and keep it on the
    # principal next to the token claims. Off by default.
    enabled: bool = False


class KeyMintingSettings(BaseModel):
    """Which tokens of an issuer may mint API keys (``keyMinting``).

    Minting turns a short-lived token into a key that lives for weeks,
    so it is limited to tokens of the listed OAuth clients (the token's
    ``azp``, else ``client_id``): typically the interactive login client
    (Swagger UI, a CLI), not service accounts or CI clients. An issuer
    without ``keyMinting`` can't mint keys at all.
    """

    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", frozen=True)

    # Client ids whose tokens may mint keys.
    clients: tuple[str, ...] = Field(min_length=1)
    # Seconds since the user's login (`auth_time`) after which minting
    # is refused until they log in again; off when unset. The issuer
    # must put `auth_time` in its access tokens.
    max_auth_age: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check_clients(self) -> KeyMintingSettings:
        """Refuse empty client ids."""
        if "" in self.clients:
            raise ValueError("keyMinting.clients must not contain an empty id")
        return self


class ClaimRuleSettings(BaseModel):
    """A claim rule of an issuer (``requiredClaim``, ``admin``).

    A principal of the issuer matches if its claim ``name`` holds one of
    ``values`` or starts with one of ``prefixes`` (see
    `poiesis.api.authz`). Prefixes are raw strings: include the
    delimiter.
    """

    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", frozen=True)

    # Claim to look up: exact name first, then a dotted path.
    name: str = Field(min_length=1)
    values: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_rule(self) -> ClaimRuleSettings:
        """Need values or prefixes, none empty (an empty prefix matches all)."""
        if not (self.values or self.prefixes):
            raise ValueError("a claim rule needs values or prefixes")
        if "" in self.values + self.prefixes:
            raise ValueError("claim rule values and prefixes must not be empty")
        return self


class IssuerSettings(BaseModel):
    """One trusted token issuer, an entry of ``POIESIS_AUTH_ISSUERS``.

    Keys are camelCase only, as in the Helm values (``auth.issuers[]``),
    also when built in code; unknown keys are refused. ``jwksUri`` skips
    OIDC discovery, for issuers that only publish keys (e.g. a gateway
    signing its own JWTs); it can't be combined with userinfo, whose
    endpoint comes from discovery.
    """

    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", frozen=True)

    # Exact `iss` of the tokens; also the discovery base URL.
    issuer: str = Field(min_length=1)
    # Accepted `aud` values: a token passes if its `aud` holds any of
    # them. A plain string is one value; several are for migrations
    # (e.g. from a shared to a per-instance audience).
    audience: tuple[str, ...] = Field(min_length=1)
    # Accepted JWT header `typ` values (RFC 9068 access tokens by
    # default), so that ID tokens and other JWTs of the issuer don't
    # pass; empty turns the check off.
    token_types: tuple[str, ...] = ("at+jwt",)
    # OAuth clients (`azp`, else `client_id`) whose tokens are accepted;
    # any client when unset.
    clients: tuple[str, ...] | None = Field(default=None, min_length=1)
    # Prefix of the owner ids of this issuer's subjects (default: the
    # issuer). Issuers may share one, e.g. the old and the new URL of a
    # renamed issuer, so that owners stay the same.
    namespace: str | None = Field(default=None, min_length=1)
    # Claim naming the subject; a dotted path walks nested objects.
    principal_claim: str = Field(default="sub", min_length=1)
    # Scopes every token of this issuer must carry.
    required_scopes: tuple[str, ...] = ()
    # Admission rule for this issuer's principals; none when unset.
    required_claim: ClaimRuleSettings | None = None
    # Built-in admin rule for this issuer's principals, only without a
    # decision service (there, admin is policy); none when unset. What an
    # admin may do is in `AuthzSettings` and the "Authorization" docs.
    admin: ClaimRuleSettings | None = None
    # Actors (RFC 8693 `act.sub` of this issuer) whose delegated tokens
    # the built-in policy accepts when there is no decision service.
    actors: tuple[str, ...] = ()
    userinfo: UserinfoSettings = Field(default_factory=UserinfoSettings)
    # Static JWKS URL; when set, discovery is skipped.
    jwks_uri: str | None = None
    # Seconds to cache the key set before fetching it again.
    jwks_cache_ttl: int = Field(default=3600, ge=1)
    # Seconds of leeway on exp / nbf / iat.
    clock_skew: int = Field(default=30, ge=0)
    # Seconds allowed for each call to the issuer (discovery, JWKS,
    # userinfo), in total.
    timeout: float = Field(default=10.0, gt=0, allow_inf_nan=False)
    # Which of its tokens may mint API keys; none when unset.
    key_minting: KeyMintingSettings | None = None

    @field_validator("audience", mode="before")
    @classmethod
    def _audience_list(cls, value: Any) -> Any:
        """Take a plain string as a one-value list."""
        return (value,) if isinstance(value, str) else value

    @property
    def owner_namespace(self) -> str:
        """The prefix of this issuer's owner ids: ``namespace`` or the issuer."""
        return self.namespace or self.issuer

    @model_validator(mode="after")
    def _check_urls(self) -> IssuerSettings:
        """Refuse settings that can't work, before any network call."""
        # The owner id is `<namespace>|<subject>` (namespace default: the
        # issuer); keep it unambiguous.
        if "|" in self.issuer:
            raise ValueError("issuer must not contain '|'")
        if self.namespace is not None and "|" in self.namespace:
            raise ValueError("namespace must not contain '|'")
        if self.jwks_uri is not None:
            if not _is_http_url(self.jwks_uri):
                raise ValueError("jwksUri must be an http(s) URL")
            if self.userinfo.enabled:
                raise ValueError(
                    "userinfo needs OIDC discovery; it can't be combined with jwksUri"
                )
        elif not _is_http_url(self.issuer):
            raise ValueError(
                "issuer must be an http(s) URL for OIDC discovery (or set jwksUri)"
            )
        for name, values in (
            ("audience", self.audience),
            ("requiredScopes", self.required_scopes),
            ("tokenTypes", self.token_types),
            ("clients", self.clients or ()),
            ("actors", self.actors),
        ):
            if any(not value.strip() for value in values):
                raise ValueError(f"{name} must not contain an empty value")
        return self


def _parse_issuers_env() -> tuple[IssuerSettings, ...]:
    """Parse ``POIESIS_AUTH_ISSUERS``, a JSON array of issuer objects.

    Empty or unset is no issuers. Also refuses any leftover
    ``POIESIS_AUTH_OIDC_*`` variable: they were replaced, and silently
    ignoring one would run with settings the operator didn't intend.
    """
    _refuse_removed_env(
        _REMOVED_ENV_PREFIX, f"{_ISSUERS_ENV} (a JSON array of issuers)"
    )
    raw = os.environ.get(_ISSUERS_ENV, "")
    if not raw.strip():
        return ()
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{_ISSUERS_ENV} is not valid JSON: {exc}") from exc
    if not isinstance(entries, list):
        message = f"{_ISSUERS_ENV} must encode a JSON array of objects"
        raise ValueError(message)  # noqa: TRY004 (a startup error, like the rest)
    issuers: list[IssuerSettings] = []
    for idx, entry in enumerate(entries):
        try:
            issuers.append(IssuerSettings.model_validate(entry))
        except ValidationError as exc:
            raise ValueError(f"{_ISSUERS_ENV}[{idx}] is invalid: {exc}") from exc
    return tuple(issuers)


def _parse_bool_env(name: str, *, default: bool) -> bool:
    """Parse an on/off env value; anything but an "off" word is true."""
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    return raw.lower() not in {"0", "false", "no", "off"}


_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _parse_strict_bool_env(name: str, *, default: bool) -> bool:
    """Parse an on/off env value; empty/unset is default, anything else raises.

    For settings where a typo must not flip the meaning (a misspelled
    "off" read as on would share tasks).
    """
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    if raw.lower() in _TRUE:
        return True
    if raw.lower() in _FALSE:
        return False
    raise ValueError(f"{name} must be true or false, got {raw!r}")


#: A key lifetime: a positive number of days or hours, at most six digits
#: (so the value always fits a ``timedelta``).
_TTL = re.compile(r"^([1-9][0-9]{0,5})([dh])$")
TTL_PATTERN = _TTL.pattern


def parse_ttl(value: str) -> timedelta:
    """Parse a key lifetime such as ``30d`` or ``12h``; raise ``ValueError``."""
    match = _TTL.match(value)
    if match is None:
        raise ValueError(
            f"invalid lifetime {value!r}: use <n>d or <n>h, e.g. 30d or 12h"
        )
    number, unit = int(match.group(1)), match.group(2)
    return timedelta(days=number) if unit == "d" else timedelta(hours=number)


def format_ttl(ttl: timedelta) -> str:
    """Format a lifetime the way :func:`parse_ttl` reads it."""
    hours = int(ttl.total_seconds()) // 3600
    return f"{hours // 24}d" if hours % 24 == 0 else f"{hours}h"


def _ttl_env(name: str, default: str) -> timedelta:
    """Parse a lifetime env value; empty/unset is ``default``."""
    raw = os.environ.get(name, "") or default
    try:
        return parse_ttl(raw)
    except ValueError as exc:
        raise ValueError(f"{name}: {exc}") from exc


class ApiKeySettings(BaseModel):
    """Poiesis API keys (see `poiesis.api.apikey_auth`); off by default.

    Keys are an add-on for clients that can't refresh tokens, such as
    workflow engines: an operator turns them on. Every key expires:
    ``default_ttl`` applies when the minting request names no lifetime,
    ``max_ttl`` caps any lifetime asked for, and an owner holds at most
    ``max_per_owner`` active keys at once.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default_factory=lambda: _parse_bool_env(
            "POIESIS_AUTH_API_KEYS_ENABLED", default=False
        ),
    )
    default_ttl: timedelta = Field(
        default_factory=lambda: _ttl_env("POIESIS_AUTH_API_KEYS_DEFAULT_TTL", "7d"),
    )
    max_ttl: timedelta = Field(
        default_factory=lambda: _ttl_env("POIESIS_AUTH_API_KEYS_MAX_TTL", "90d"),
    )
    max_per_owner: int = Field(
        default_factory=lambda: (
            _parse_int_env("POIESIS_AUTH_API_KEYS_MAX_PER_OWNER", 20) or 0
        ),
    )

    @model_validator(mode="after")
    def _check_limits(self) -> ApiKeySettings:
        """Refuse limits that can't hold: non-positive or default above max."""
        if self.default_ttl <= timedelta(0) or self.max_ttl <= timedelta(0):
            raise ValueError("API key lifetimes must be positive")
        if self.default_ttl > self.max_ttl:
            raise ValueError(
                "POIESIS_AUTH_API_KEYS_DEFAULT_TTL "
                f"({format_ttl(self.default_ttl)}) exceeds "
                f"POIESIS_AUTH_API_KEYS_MAX_TTL ({format_ttl(self.max_ttl)})"
            )
        if self.max_per_owner < 1:
            raise ValueError("POIESIS_AUTH_API_KEYS_MAX_PER_OWNER must be at least 1")
        return self


class SwaggerUiSettings(BaseModel):
    """The login offered by the Swagger UI at ``/docs``, for minting keys.

    Documentation only: the UI gets an OpenID Connect scheme (authorization
    code with PKCE, from ``issuer``'s discovery document) and the public
    client ``client_id``; the tokens it obtains are validated like any
    other, by the authenticator chain.
    """

    model_config = ConfigDict(frozen=True)

    # One of the configured issuers (exact match), with OIDC discovery.
    issuer: str = Field(min_length=1)
    # A public client of that issuer allowing <api>/docs/oauth2-redirect.
    client_id: str = Field(min_length=1)
    # Space-separated scopes the UI asks for.
    scopes: str = Field(default="openid", min_length=1)


def _parse_swagger_ui_env() -> SwaggerUiSettings | None:
    """Parse ``POIESIS_AUTH_SWAGGER_UI_*``; no issuer and no client is off."""
    issuer = os.environ.get("POIESIS_AUTH_SWAGGER_UI_ISSUER", "")
    client_id = os.environ.get("POIESIS_AUTH_SWAGGER_UI_CLIENT_ID", "")
    scopes = os.environ.get("POIESIS_AUTH_SWAGGER_UI_SCOPES", "") or "openid"
    if not issuer and not client_id:
        return None
    if not (issuer and client_id):
        raise ValueError(
            "the Swagger UI login needs both POIESIS_AUTH_SWAGGER_UI_ISSUER "
            "and POIESIS_AUTH_SWAGGER_UI_CLIENT_ID"
        )
    return SwaggerUiSettings(issuer=issuer, client_id=client_id, scopes=scopes)


class AuthSettings(BaseModel):
    """Resource-server settings: the trusted token issuers.

    Poiesis validates incoming JWTs against each configured issuer's
    keys; it is not an OAuth client. When ``enabled`` is true at least
    one issuer is required, and issuers must be unique; misconfiguration
    fails loudly rather than silently disabling auth. When ``enabled``
    is false the API serves all requests as a fixed anonymous principal.
    """

    enabled: bool = Field(
        default_factory=lambda: _parse_bool_env("POIESIS_AUTH_ENABLED", default=True),
    )
    issuers: tuple[IssuerSettings, ...] = Field(default_factory=_parse_issuers_env)
    api_keys: ApiKeySettings = Field(default_factory=ApiKeySettings)
    swagger_ui: SwaggerUiSettings | None = Field(default_factory=_parse_swagger_ui_env)
    # Public URL of this Poiesis (RFC 9728 resource identifier), e.g.
    # https://poiesis.example.org; unset serves no resource metadata.
    resource: str | None = Field(
        default_factory=lambda: os.environ.get("POIESIS_AUTH_RESOURCE") or None,
        validate_default=True,
    )

    @field_validator("resource")
    @classmethod
    def _check_resource(cls, value: str | None) -> str | None:
        """Take an http(s) URL without query, fragment or credentials.

        A trailing ``/`` is dropped: clients compare the identifier
        exactly, and ``https://host`` is the usual spelling.
        """
        if value is None:
            return None
        if (
            not _is_http_url(value)
            or any(c in value for c in "?#")
            or "@" in urlsplit(value).netloc
            # Quoted in WWW-Authenticate (no quotes, backslashes, spaces)
            # and a route path (no braces).
            or re.search(r'[\s"\\{}]', value)
        ):
            raise ValueError(
                "POIESIS_AUTH_RESOURCE must be an http(s) URL without query, "
                "fragment or credentials, e.g. https://poiesis.example.org"
            )
        return value.rstrip("/")

    @model_validator(mode="after")
    def _check_issuers(self) -> AuthSettings:
        """Need at least one issuer when enabled, and no issuer twice."""
        if self.enabled and not self.issuers:
            raise ValueError(
                f"auth is enabled but {_ISSUERS_ENV} lists no issuer; "
                "configure one or set POIESIS_AUTH_ENABLED=false"
            )
        seen: dict[str, IssuerSettings] = {}
        for entry in self.issuers:
            if entry.issuer in seen:
                raise ValueError(f"{_ISSUERS_ENV} lists {entry.issuer!r} twice")
            seen[entry.issuer] = entry
        if self.enabled:
            _warn_shared_namespaces(self.issuers)
        if self.enabled and self.swagger_ui is not None:
            # The UI reads the issuer's discovery document in the browser.
            login = seen.get(self.swagger_ui.issuer)
            if login is None:
                raise ValueError(
                    f"POIESIS_AUTH_SWAGGER_UI_ISSUER {self.swagger_ui.issuer!r} "
                    f"is not one of the issuers in {_ISSUERS_ENV}"
                )
            if login.jwks_uri is not None:
                raise ValueError(
                    "POIESIS_AUTH_SWAGGER_UI_ISSUER needs OIDC discovery; "
                    f"{login.issuer!r} is configured with jwksUri"
                )
        return self


def _warn_shared_namespaces(issuers: tuple[IssuerSettings, ...]) -> None:
    """Warn about issuers that share an owner namespace.

    Allowed on purpose (a renamed issuer keeps its owners by sharing the
    old URL's namespace), but equal subjects of such issuers are then
    one owner, with the same tasks and keys: that must not happen by
    accident.
    """
    by_namespace: dict[str, list[str]] = {}
    for entry in issuers:
        by_namespace.setdefault(entry.owner_namespace, []).append(entry.issuer)
    for namespace, names in by_namespace.items():
        if len(names) > 1:
            logger.warning(
                "Issuers %s share the owner namespace %r, so equal subjects of "
                "them are one owner; intended only for one issuer under several "
                "URLs, otherwise give each its own namespace",
                ", ".join(names),
                namespace,
            )


class AuthzSettings(BaseModel):
    """Authorization settings: the decision service, off by default.

    Claim rules are set per issuer (``IssuerSettings.required_claim``
    and ``admin``). ``sharing`` lets the decision service show tasks to
    others than their owner (off: owner-only, whatever it answers);
    ``max_owners`` caps the owners one list scope may name.
    ``admin_read`` gives the built-in admins (no decision service) read
    and cancel of every task (off: admins see their own tasks only). See
    ``poiesis.api.authz`` and the "Authorization" docs page.
    """

    decision_service_url: str = Field(
        default_factory=lambda: os.environ.get(
            "POIESIS_AUTHZ_DECISION_SERVICE_URL", ""
        ),
    )
    decision_service_timeout: float = Field(
        default_factory=lambda: _parse_seconds_env(
            "POIESIS_AUTHZ_DECISION_SERVICE_TIMEOUT", 2.0
        ),
        gt=0,
        allow_inf_nan=False,
    )
    decision_service_claims: tuple[str, ...] = Field(
        default_factory=lambda: _parse_json_strings_env(
            "POIESIS_AUTHZ_DECISION_SERVICE_CLAIMS"
        ),
    )
    decision_service_credential_file: str = Field(
        default_factory=lambda: os.environ.get(
            "POIESIS_AUTHZ_DECISION_SERVICE_CREDENTIAL_FILE", ""
        ),
    )
    sharing: bool = Field(
        default_factory=lambda: _parse_strict_bool_env(
            "POIESIS_AUTHZ_SHARING", default=False
        ),
    )
    max_owners: int = Field(
        default_factory=lambda: _parse_int_env("POIESIS_AUTHZ_MAX_OWNERS", 1000) or 0,
        ge=1,
        # Defaults aren't validated otherwise, and this one comes from env.
        validate_default=True,
    )
    # Strict like sharing: a misspelled "off" must not open every task.
    admin_read: bool = Field(
        default_factory=lambda: _parse_strict_bool_env(
            "POIESIS_AUTHZ_ADMIN_READ", default=False
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _refuse_global_claim_rule(cls, data: Any) -> Any:
        """Refuse a leftover ``POIESIS_AUTHZ_REQUIRED_CLAIM_*`` variable.

        The global claim rule matched the value whichever issuer the
        token came from; rules are now set per issuer.
        """
        _refuse_removed_env(
            _REMOVED_CLAIM_ENV_PREFIX,
            f"auth.issuers[].requiredClaim (requiredClaim in {_ISSUERS_ENV}), "
            "which applies to that issuer's tokens only",
        )
        return data

    def validate_for(self, *, auth_enabled: bool) -> None:
        """Refuse configurations that would not do what they say.

        Called at app startup: authorization without authentication (no
        real subject could reach a decision, nor be an admin), decision
        service settings without a URL (sharing included: only a decision
        service shares), and a URL that isn't http(s).
        """
        service = (
            self.decision_service_url,
            self.decision_service_claims,
            self.decision_service_credential_file,
            self.sharing,
        )
        if not auth_enabled and (any(service) or self.admin_read):
            raise ValueError("POIESIS_AUTHZ_* is set but auth is disabled")
        try:
            url = httpx.URL(self.decision_service_url)
        except httpx.InvalidURL:
            url = httpx.URL()
        if any(service) and (url.scheme not in {"http", "https"} or not url.host):
            raise ValueError(
                "POIESIS_AUTHZ_DECISION_SERVICE_* needs an http(s) "
                "POIESIS_AUTHZ_DECISION_SERVICE_URL"
            )


class AuditSettings(BaseModel):
    """The audit log (see `poiesis.api.audit`): on by default."""

    # Strict: a typo must not silently turn the audit trail off.
    enabled: bool = Field(
        default_factory=lambda: _parse_strict_bool_env(
            "POIESIS_AUDIT_ENABLED", default=True
        ),
    )


_SERVICE_INFO_ENV = "POIESIS_SERVICE_INFO_"


def _service_info_env(name: str) -> str | None:
    """Read ``POIESIS_SERVICE_INFO_<name>``; empty or unset is ``None``."""
    return os.environ.get(_SERVICE_INFO_ENV + name, "").strip() or None


def _check_service_url(
    value: str | None, name: str, *, mailto: bool = False
) -> str | None:
    """Take an absolute http(s) URL (or a ``mailto:`` one, if allowed).

    It must also be a valid `AnyUrl`, as the service info's model has it.
    """
    if value is None:
        return None
    is_mailto = mailto and value.startswith("mailto:") and value != "mailto:"
    if not re.search(r"\s", value) and (_is_http_url(value) or is_mailto):
        with contextlib.suppress(ValueError):
            AnyUrl(value)
            return value
    kinds = "an http(s) or mailto: URL" if mailto else "an http(s) URL"
    raise ValueError(f"{_SERVICE_INFO_ENV}{name} must be {kinds}, got {value!r}")


class ServiceInfoSettings(BaseModel):
    """The deployment's own fields of ``GET /service-info``.

    ``None`` keeps the built-in value (see `poiesis.api.routes.service_info`):
    ``environment`` is then left out and ``createdAt`` is the time of the
    request, as before. ``id`` has its default here: it is also the
    service id sent to the decision service.
    """

    id: str = Field(
        default_factory=lambda: (
            _service_info_env("ID") or get_poiesis_api_constants().SERVICE_ID
        ),
        min_length=1,
    )
    name: str | None = Field(
        default_factory=lambda: _service_info_env("NAME"), min_length=1
    )
    description: str | None = Field(
        default_factory=lambda: _service_info_env("DESCRIPTION"), min_length=1
    )
    organization_name: str | None = Field(
        default_factory=lambda: _service_info_env("ORGANIZATION_NAME"), min_length=1
    )
    organization_url: str | None = Field(
        default_factory=lambda: _service_info_env("ORGANIZATION_URL"),
        validate_default=True,
    )
    contact_url: str | None = Field(
        default_factory=lambda: _service_info_env("CONTACT_URL"),
        validate_default=True,
    )
    documentation_url: str | None = Field(
        default_factory=lambda: _service_info_env("DOCUMENTATION_URL"),
        validate_default=True,
    )
    # Free text; the spec suggests prod, test, dev or staging.
    environment: str | None = Field(
        default_factory=lambda: _service_info_env("ENVIRONMENT"), min_length=1
    )
    created_at: datetime | None = Field(
        default_factory=lambda: _service_info_env("CREATED_AT"),
        validate_default=True,
    )

    @field_validator("organization_url")
    @classmethod
    def _check_organization_url(cls, value: str | None) -> str | None:
        """Take an http(s) URL."""
        return _check_service_url(value, "ORGANIZATION_URL")

    @field_validator("documentation_url")
    @classmethod
    def _check_documentation_url(cls, value: str | None) -> str | None:
        """Take an http(s) URL."""
        return _check_service_url(value, "DOCUMENTATION_URL")

    @field_validator("contact_url")
    @classmethod
    def _check_contact_url(cls, value: str | None) -> str | None:
        """Take an http(s) URL, or an email address as a ``mailto:`` URL."""
        return _check_service_url(value, "CONTACT_URL", mailto=True)

    @field_validator("created_at", mode="before")
    @classmethod
    def _check_created_at(cls, value: object) -> datetime | None:
        """Take an ISO 8601 date and time with a UTC offset (RFC 3339)."""
        if value is None:
            return None
        parsed: datetime | None = None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            with contextlib.suppress(ValueError):
                parsed = datetime.fromisoformat(value)
        if parsed is None or parsed.tzinfo is None:
            raise ValueError(
                f"{_SERVICE_INFO_ENV}CREATED_AT must be an ISO 8601 date and "
                f"time with a UTC offset, e.g. 2026-01-15T09:00:00Z, got {value!r}"
            )
        return parsed


class Settings(BaseModel):
    """API runtime settings."""

    database_url: str = Field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/poiesis",
        ),
    )
    poiesis_namespace: str = Field(
        default_factory=lambda: os.environ.get("POIESIS_NAMESPACE", "poiesis"),
    )
    # Defaults to poiesis_namespace via runtime_config() — operators can split
    # the control plane from the workload ns by setting POIESIS_TASKPOD_NAMESPACE.
    taskpod_namespace: str | None = Field(
        default_factory=lambda: os.environ.get("POIESIS_TASKPOD_NAMESPACE") or None,
    )
    poiesis_image: str = Field(
        default_factory=lambda: os.environ.get("POIESIS_IMAGE", DEFAULT_POIESIS_IMAGE),
    )
    # PVC storage class. Three states:
    #   None  → omit storageClassName, defer to cluster default
    #   ""    → explicit "no provisioning" (matches kubectl '-' sentinel
    #           which the chart converts to ""); requires a pre-bound PV
    #   other → use that StorageClass
    pvc_storage_class: str | None = Field(
        default_factory=lambda: (
            None
            if os.environ.get("POIESIS_PVC_STORAGE_CLASS") is None
            else os.environ.get("POIESIS_PVC_STORAGE_CLASS", "")
        ),
    )
    pvc_access_modes: tuple[str, ...] = Field(
        default_factory=lambda: _parse_csv_env(
            "POIESIS_PVC_ACCESS_MODES", default=("ReadWriteOnce",)
        ),
    )
    pvc_default_size_gi: int = Field(
        default_factory=lambda: _parse_int_env("POIESIS_PVC_DEFAULT_SIZE_GI", 1) or 1,
    )
    # None disables the cap entirely. Production charts MUST set this; the
    # schema enforces presence at chart-install time.
    pvc_max_size_gi: int | None = Field(
        default_factory=lambda: _parse_optional_int_env("POIESIS_PVC_MAX_SIZE_GI"),
    )
    pvc_labels: dict[str, str] = Field(
        default_factory=lambda: _parse_json_object_env("POIESIS_PVC_LABELS"),
    )
    pvc_annotations: dict[str, str] = Field(
        default_factory=lambda: _parse_json_object_env("POIESIS_PVC_ANNOTATIONS"),
    )
    # None → ttlSecondsAfterFinished is omitted on the Job entirely (audit
    # retention). Default 3600s matches the prior hardcoded behaviour.
    job_ttl_seconds: int | None = Field(
        default_factory=lambda: (
            _parse_optional_int_env("POIESIS_JOB_TTL_SECONDS")
            if "POIESIS_JOB_TTL_SECONDS" in os.environ
            else 3600
        ),
    )
    # Task time limit: activeDeadlineSeconds on the Job. None → no limit.
    # Strict: a typo must not change how long tasks may run.
    active_deadline_seconds: int | None = Field(
        default_factory=lambda: _parse_time_limit_env(
            "POIESIS_ACTIVE_DEADLINE_SECONDS", 3600
        ),
    )
    taskpod_service_account: str | None = Field(
        default_factory=lambda: (
            os.environ.get("POIESIS_TASKPOD_SERVICE_ACCOUNT") or None
        ),
    )
    pod_security_enforce: PodSecurityEnforce = Field(
        default_factory=lambda: PodSecurityEnforce(
            os.environ.get("POIESIS_POD_SECURITY_ENFORCE", "restricted")
        ),
    )
    # Comma-separated list of Secrets to attach as imagePullSecrets on every TaskPod.
    image_pull_secrets: tuple[str, ...] = Field(
        default_factory=lambda: tuple(
            s.strip()
            for s in os.environ.get("POIESIS_IMAGE_PULL_SECRETS", "").split(",")
            if s.strip()
        ),
    )
    postgres_ca_configmap: str | None = Field(
        default_factory=lambda: os.environ.get("POIESIS_POSTGRES_CA_CONFIGMAP") or None,
    )
    # Operator-supplied TaskPod extensions, JSON-encoded via the chart.
    # All three are rejected on collision with chart-internal names at
    # construction so the api pod fails fast on misconfiguration.
    taskpod_extra_env: list[dict[str, Any]] = Field(
        default_factory=_parse_and_check_env_extras,
    )
    taskpod_extra_volumes: list[dict[str, Any]] = Field(
        default_factory=lambda: _parse_and_check_volume_extras(
            "POIESIS_TASKPOD_EXTRA_VOLUMES"
        ),
    )
    taskpod_extra_volume_mounts: list[dict[str, Any]] = Field(
        default_factory=lambda: _parse_and_check_volume_extras(
            "POIESIS_TASKPOD_EXTRA_VOLUME_MOUNTS"
        ),
    )
    # Strict: a typo must not turn on uploading a whole path_prefix.
    output_glob_fallback: bool = Field(
        default_factory=lambda: _parse_strict_bool_env(
            OUTPUT_GLOB_FALLBACK_ENV, default=False
        ),
    )
    # Directories `file://` URLs may point into; empty turns the scheme off.
    file_url_roots: tuple[str, ...] = Field(
        default_factory=lambda: parse_file_url_roots(
            os.environ.get(FILE_URL_ROOTS_ENV)
        ),
    )
    # Resources of the poiesis-owned TaskPod containers (JSON resources
    # blocks); unset leaves them without requests or limits.
    recorder_resources: dict[str, dict[str, str]] | None = Field(
        default_factory=lambda: _parse_resources_env(RECORDER_RESOURCES_ENV),
    )
    filer_resources: dict[str, dict[str, str]] | None = Field(
        default_factory=lambda: _parse_resources_env(FILER_RESOURCES_ENV),
    )
    ack_resources: dict[str, dict[str, str]] | None = Field(
        default_factory=lambda: _parse_resources_env(ACK_RESOURCES_ENV),
    )
    aws_endpoint_url: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_ENDPOINT_URL") or None,
    )
    aws_access_key_id: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_ACCESS_KEY_ID") or None,
    )
    aws_secret_access_key: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_SECRET_ACCESS_KEY") or None,
    )
    aws_session_token: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_SESSION_TOKEN") or None,
    )
    aws_region: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_REGION") or None,
    )
    # Secrets in the TaskPod namespace that trec/tif/tof read their
    # credentials from. Unset: the values are copied into each Job spec.
    taskpod_database_secret: str | None = Field(
        default_factory=lambda: (
            os.environ.get("POIESIS_TASKPOD_DATABASE_SECRET") or None
        ),
    )
    taskpod_database_secret_key: str = Field(
        default_factory=lambda: (
            os.environ.get("POIESIS_TASKPOD_DATABASE_SECRET_KEY") or "DATABASE_URL"
        ),
    )
    taskpod_s3_secret: str | None = Field(
        default_factory=lambda: os.environ.get("POIESIS_TASKPOD_S3_SECRET") or None,
    )
    auth: AuthSettings = Field(default_factory=AuthSettings)
    authz: AuthzSettings = Field(default_factory=AuthzSettings)
    audit: AuditSettings = Field(default_factory=AuditSettings)
    service_info: ServiceInfoSettings = Field(default_factory=ServiceInfoSettings)

    def runtime_config(self) -> RuntimeConfig:
        """Materialise the TaskPod RuntimeConfig used by the spec builder."""
        env = self._credential_env()
        # Not secret, so literal values.
        for name, value in (
            ("AWS_ENDPOINT_URL", self.aws_endpoint_url),
            ("AWS_REGION", self.aws_region),
        ):
            if value is not None:
                env.append(V1EnvVar(name=name, value=value))
        return RuntimeConfig(
            taskpod_namespace=self.taskpod_namespace or self.poiesis_namespace,
            poiesis_image=self.poiesis_image,
            pvc_storage_class=self.pvc_storage_class,
            pvc_access_modes=self.pvc_access_modes,
            pvc_default_size_gi=self.pvc_default_size_gi,
            pvc_max_size_gi=self.pvc_max_size_gi,
            pvc_labels=self.pvc_labels,
            pvc_annotations=self.pvc_annotations,
            taskpod_service_account=self.taskpod_service_account,
            job_ttl_seconds=self.job_ttl_seconds,
            active_deadline_seconds=self.active_deadline_seconds,
            pod_security_enforce=self.pod_security_enforce,
            image_pull_secrets=self.image_pull_secrets,
            postgres_ca_configmap=self.postgres_ca_configmap,
            extra_env=env,
            taskpod_extra_env=_entries_to_envvars(self.taskpod_extra_env),
            taskpod_extra_volumes=self.taskpod_extra_volumes,
            taskpod_extra_volume_mounts=self.taskpod_extra_volume_mounts,
            output_glob_fallback=self.output_glob_fallback,
            file_url_roots=self.file_url_roots,
            recorder_resources=_resources(self.recorder_resources),
            filer_resources=_resources(self.filer_resources),
            ack_resources=_resources(self.ack_resources),
        )

    def _credential_env(self) -> list[V1EnvVar]:
        """Database URL and S3 credentials for trec, tif and tof.

        References to Secrets in the TaskPod namespace when their names are
        set, so no value reaches a Job or Pod spec. Otherwise (local runs)
        the API's own values are copied in, with one warning.
        """
        env: list[V1EnvVar] = []
        copied: list[str] = []
        if self.taskpod_database_secret:
            env.append(
                _secret_env(
                    "DATABASE_URL",
                    self.taskpod_database_secret,
                    self.taskpod_database_secret_key,
                )
            )
        else:
            env.append(V1EnvVar(name="DATABASE_URL", value=self.database_url))
            copied.append("DATABASE_URL")
        if self.taskpod_s3_secret:
            secret = self.taskpod_s3_secret
            # Only temporary credentials have a session token, so its key
            # is optional.
            env.extend(
                (
                    _secret_env("AWS_ACCESS_KEY_ID", secret, "AWS_ACCESS_KEY_ID"),
                    _secret_env(
                        "AWS_SECRET_ACCESS_KEY", secret, "AWS_SECRET_ACCESS_KEY"
                    ),
                    _secret_env(
                        "AWS_SESSION_TOKEN",
                        secret,
                        "AWS_SESSION_TOKEN",
                        optional=True,
                    ),
                )
            )
        else:
            # Propagate s3 creds only when set; tasks with no s3 i/o don't
            # need them.
            for name, value in (
                ("AWS_ACCESS_KEY_ID", self.aws_access_key_id),
                ("AWS_SECRET_ACCESS_KEY", self.aws_secret_access_key),
                ("AWS_SESSION_TOKEN", self.aws_session_token),
            ):
                if value is not None:
                    env.append(V1EnvVar(name=name, value=value))
                    copied.append(name)
        if copied:
            logger.warning(
                "Copying %s into every TaskPod Job spec as plain values: anyone "
                "who can read Jobs or Pods in the TaskPod namespace can read "
                "them. Set POIESIS_TASKPOD_DATABASE_SECRET and "
                "POIESIS_TASKPOD_S3_SECRET to reference Secrets instead.",
                ", ".join(copied),
            )
        return env


def load_settings() -> Settings:
    """Construct Settings from the current process environment."""
    return Settings()
