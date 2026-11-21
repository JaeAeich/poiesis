"""API-side settings derived from environment variables.

Single place that reads env. Held in a Pydantic settings object so the
TaskPod RuntimeConfig and the database DSN come from one validated source.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import timedelta
from typing import Any

import httpx
from kubernetes.client import V1EnvVar
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)
from pydantic.alias_generators import to_camel

from poiesis.core.taskpod import PodSecurityEnforce, RuntimeConfig

logger = logging.getLogger(__name__)


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


DEFAULT_POIESIS_IMAGE = "docker.io/jaeaeich/poiesis:latest"


_ISSUERS_ENV = "POIESIS_AUTH_ISSUERS"
_REMOVED_ENV_PREFIX = "POIESIS_AUTH_OIDC_"


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
    # Expected `aud` claim.
    audience: str = Field(min_length=1)
    # Claim naming the subject; a dotted path walks nested objects.
    principal_claim: str = Field(default="sub", min_length=1)
    # Scopes every token of this issuer must carry.
    required_scopes: tuple[str, ...] = ()
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

    @model_validator(mode="after")
    def _check_urls(self) -> IssuerSettings:
        """Refuse settings that can't work, before any network call."""
        if "|" in self.issuer:
            # The owner id is `issuer|subject`; keep it unambiguous.
            raise ValueError("issuer must not contain '|'")
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
        if "" in self.required_scopes:
            raise ValueError("requiredScopes must not contain an empty scope")
        return self


def _parse_issuers_env() -> tuple[IssuerSettings, ...]:
    """Parse ``POIESIS_AUTH_ISSUERS``, a JSON array of issuer objects.

    Empty or unset is no issuers. Also refuses any leftover
    ``POIESIS_AUTH_OIDC_*`` variable: they were replaced, and silently
    ignoring one would run with settings the operator didn't intend.
    """
    removed = sorted(n for n in os.environ if n.startswith(_REMOVED_ENV_PREFIX))
    if removed:
        raise ValueError(
            ", ".join(removed) + f" is no longer read: {_REMOVED_ENV_PREFIX}* was "
            f"replaced by {_ISSUERS_ENV} (a JSON array of issuers)"
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


class AuthzSettings(BaseModel):
    """Authorization settings: the claim rule and the decision service.

    Both are off by default. See ``poiesis.api.authz`` and the
    "Authorization" docs page.
    """

    required_claim_name: str = Field(
        default_factory=lambda: os.environ.get("POIESIS_AUTHZ_REQUIRED_CLAIM_NAME", ""),
    )
    required_claim_values: tuple[str, ...] = Field(
        default_factory=lambda: _parse_json_strings_env(
            "POIESIS_AUTHZ_REQUIRED_CLAIM_VALUES"
        ),
    )
    required_claim_prefixes: tuple[str, ...] = Field(
        default_factory=lambda: _parse_json_strings_env(
            "POIESIS_AUTHZ_REQUIRED_CLAIM_PREFIXES"
        ),
    )
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

    def validate_for(self, *, auth_enabled: bool) -> None:
        """Refuse configurations that would not do what they say.

        Called at app startup: authorization without authentication (no
        real subject could reach a decision), an incomplete claim rule or
        one with empty values or prefixes (an empty prefix admits
        everyone), decision service settings without a URL, and a URL
        that isn't http(s).
        """
        rule = (
            self.required_claim_name,
            self.required_claim_values,
            self.required_claim_prefixes,
        )
        service = (
            self.decision_service_url,
            self.decision_service_claims,
            self.decision_service_credential_file,
        )
        if not auth_enabled and any(rule + service):
            raise ValueError("POIESIS_AUTHZ_* is set but auth is disabled")
        if any(rule) and not (
            self.required_claim_name
            and (self.required_claim_values or self.required_claim_prefixes)
        ):
            raise ValueError(
                "the claim rule needs POIESIS_AUTHZ_REQUIRED_CLAIM_NAME and "
                "POIESIS_AUTHZ_REQUIRED_CLAIM_VALUES or _PREFIXES"
            )
        if "" in self.required_claim_values + self.required_claim_prefixes:
            raise ValueError("the claim rule's values and prefixes must not be empty")
        try:
            url = httpx.URL(self.decision_service_url)
        except httpx.InvalidURL:
            url = httpx.URL()
        if any(service) and (url.scheme not in {"http", "https"} or not url.host):
            raise ValueError(
                "POIESIS_AUTHZ_DECISION_SERVICE_* needs an http(s) "
                "POIESIS_AUTHZ_DECISION_SERVICE_URL"
            )


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
    aws_endpoint_url: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_ENDPOINT_URL") or None,
    )
    aws_access_key_id: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_ACCESS_KEY_ID") or None,
    )
    aws_secret_access_key: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_SECRET_ACCESS_KEY") or None,
    )
    aws_region: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_REGION") or None,
    )
    auth: AuthSettings = Field(default_factory=AuthSettings)
    authz: AuthzSettings = Field(default_factory=AuthzSettings)

    def runtime_config(self) -> RuntimeConfig:
        """Materialise the TaskPod RuntimeConfig used by the spec builder."""
        env = [V1EnvVar(name="DATABASE_URL", value=self.database_url)]
        # Propagate s3 creds only when set; tasks with no s3 i/o don't need them.
        for name, value in (
            ("AWS_ENDPOINT_URL", self.aws_endpoint_url),
            ("AWS_ACCESS_KEY_ID", self.aws_access_key_id),
            ("AWS_SECRET_ACCESS_KEY", self.aws_secret_access_key),
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
            pod_security_enforce=self.pod_security_enforce,
            image_pull_secrets=self.image_pull_secrets,
            postgres_ca_configmap=self.postgres_ca_configmap,
            extra_env=env,
            taskpod_extra_env=_entries_to_envvars(self.taskpod_extra_env),
            taskpod_extra_volumes=self.taskpod_extra_volumes,
            taskpod_extra_volume_mounts=self.taskpod_extra_volume_mounts,
        )


def load_settings() -> Settings:
    """Construct Settings from the current process environment."""
    return Settings()
