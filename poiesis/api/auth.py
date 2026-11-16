"""OIDC authentication: JWT validation and the per-request principal.

Poiesis is a resource server: it does not run an OAuth login flow. It
trusts JWTs minted by a single configured issuer, fetched and cached
from the issuer's JWKS endpoint. The validated identity is exposed to
route handlers as :class:`Principal` via the :func:`get_principal`
FastAPI dependency.

Note: this module does NOT use ``from __future__ import annotations``.
FastAPI introspects the signature of :func:`get_principal` at runtime
to wire dependency injection, so ``Request`` must be a live import,
not a string forward reference. Same constraint as `poiesis.api.deps`.
"""

import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx
from fastapi import Request
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from poiesis.api.exceptions import ForbiddenError, UnauthorizedError

if TYPE_CHECKING:
    from poiesis.api.settings import AuthSettings

logger = logging.getLogger(__name__)

#: Fixed principal id served to every request when ``auth.enabled`` is
#: false. Chosen so it can never collide with a real OIDC ``sub``
#: claim (which is always a non-empty string per the spec, but in
#: practice operators may use anything).
ANONYMOUS_PRINCIPAL_ID = "__anonymous__"

_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"
#: Userinfo responses are cached per token until the token expires, but
#: at most this many seconds (bounds the lag after a revocation) ...
_USERINFO_MAX_AGE = 300.0
#: ... and for at most this many tokens; the least recently used go first.
_USERINFO_CACHE_SIZE = 4096
_USERINFO_TIMEOUT = 5.0
_BEARER_PREFIX = "Bearer "
_DEFAULT_ALGORITHMS: tuple[str, ...] = (
    "RS256",
    "RS384",
    "RS512",
    "ES256",
    "ES384",
    "ES512",
    "PS256",
    "PS384",
    "PS512",
)


@dataclass(slots=True, frozen=True)
class Principal:
    """The authenticated subject of a request.

    ``id`` is the value of the configured ``principal_claim`` (default
    ``sub``). ``claims`` carries the full validated JWT payload so
    downstream code can inspect arbitrary fields without re-parsing the
    token. ``userinfo`` holds the issuer's userinfo response when
    ``POIESIS_AUTH_OIDC_USERINFO_ENABLED`` is on (empty otherwise), kept
    apart from the token claims.
    """

    id: str
    claims: dict[str, Any] = field(default_factory=dict)
    userinfo: dict[str, Any] = field(default_factory=dict)

    def claim(self, name: str) -> Any:
        """Return the caller's value of claim ``name``, or ``None``.

        The exact top-level name comes before a dotted path (so
        URI-named claims such as ``https://example.org/groups`` work),
        and at each step the access token comes before userinfo.
        """
        for source in (self.claims, self.userinfo):
            if source.get(name) is not None:
                return source[name]
        for source in (self.claims, self.userinfo):
            value = _walk_claim_path(source, name)
            if value is not None:
                return value
        return None


class OIDCValidator:
    """Validates JWTs against a single OIDC issuer.

    Built once at app startup. JWKS is fetched on first use and
    refreshed lazily after ``jwks_cache_ttl`` seconds. The discovery
    document is fetched once at startup so misconfiguration fails
    loudly before the first request lands.
    """

    def __init__(self, settings: "AuthSettings") -> None:
        """Capture settings; defer network calls to :meth:`bootstrap`."""
        settings.validate_required()
        self._settings = settings
        self._jwks_uri: str | None = None
        self._userinfo_uri: str | None = None
        self._userinfo_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = (
            OrderedDict()
        )
        self._issuer_from_discovery: str | None = None
        self._jwks: KeySet | None = None
        self._jwks_fetched_at: float = 0.0
        self._algorithms = list(_DEFAULT_ALGORITHMS)

    async def bootstrap(self) -> None:
        """Fetch OIDC discovery and prime the JWKS cache.

        Called from the FastAPI ``lifespan``. Any failure here aborts
        startup — the operator sees a clear error rather than a half-
        configured server that returns 401 on every request.
        """
        url = self._settings.issuer.rstrip("/") + _DISCOVERY_SUFFIX
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            doc = resp.json()
        self._issuer_from_discovery = doc.get("issuer") or self._settings.issuer
        self._jwks_uri = doc["jwks_uri"]
        if self._settings.userinfo_enabled:
            self._userinfo_uri = self._checked_userinfo_uri(
                doc.get("userinfo_endpoint")
            )
        await self._refresh_jwks()
        logger.info(
            "OIDC discovery ok: issuer=%s jwks_uri=%s",
            self._issuer_from_discovery,
            self._jwks_uri,
        )

    def _checked_userinfo_uri(self, uri: Any) -> str:
        """Return the discovered userinfo endpoint if tokens may go there.

        It must be an absolute ``https`` URL, or ``http`` if the issuer
        is ``http`` too (e.g. a development IdP), so that tokens never
        travel less protected than the operator chose for the issuer.
        """
        parts = urlsplit(uri) if isinstance(uri, str) else None
        allowed = {"https", urlsplit(self._settings.issuer).scheme}
        if parts is None or parts.scheme not in allowed or not parts.netloc:
            raise RuntimeError(
                "POIESIS_AUTH_OIDC_USERINFO_ENABLED is on but the issuer's "
                "discovery document has no usable userinfo_endpoint"
            )
        return uri

    @property
    def userinfo_enabled(self) -> bool:
        """Whether principals carry the issuer's userinfo response."""
        return self._userinfo_uri is not None

    async def userinfo(self, token: str, claims: dict[str, Any]) -> dict[str, Any]:
        """Return the userinfo response for a validated token.

        Cached per token (by hash) until the token expires, at most
        ``_USERINFO_MAX_AGE`` seconds. Fails closed: any failure, and a
        ``sub`` that differs from the token's, raises
        :class:`UnauthorizedError`.
        """
        key = hashlib.sha256(token.encode()).hexdigest()
        now = time.time()
        cached = self._userinfo_cache.get(key)
        if cached is not None and cached[0] > now:
            self._userinfo_cache.move_to_end(key)
            return cached[1]

        info = await self._fetch_userinfo(token)
        sub = claims.get("sub")
        if not isinstance(sub, str) or info.get("sub") != sub:
            logger.warning("Userinfo sub does not match the token's sub")
            raise UnauthorizedError("userinfo lookup failed")

        expires = claims.get("exp")
        until = now + _USERINFO_MAX_AGE
        if isinstance(expires, int | float):
            until = min(until, float(expires))
        self._userinfo_cache[key] = (until, info)
        self._userinfo_cache.move_to_end(key)
        while len(self._userinfo_cache) > _USERINFO_CACHE_SIZE:
            self._userinfo_cache.popitem(last=False)
        return info

    async def _fetch_userinfo(self, token: str) -> dict[str, Any]:
        """GET the userinfo endpoint with ``token``; any failure is a 401.

        Only plain JSON is accepted: signed or encrypted userinfo
        (``application/jwt``) is not supported.
        """
        try:
            async with httpx.AsyncClient(timeout=_USERINFO_TIMEOUT) as client:
                resp = await client.get(
                    self._userinfo_uri or "",
                    headers={
                        "Authorization": _BEARER_PREFIX + token,
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning("Userinfo request failed: %s", type(exc).__name__)
            raise UnauthorizedError("userinfo lookup failed") from exc
        content_type = resp.headers.get("content-type", "")
        info: Any = None
        if resp.status_code == httpx.codes.OK and content_type.startswith(
            "application/json"
        ):
            try:
                info = resp.json()
            except ValueError:
                info = None
        if not isinstance(info, dict):
            logger.warning(
                "Userinfo endpoint answered %s (%s) without a JSON object",
                resp.status_code,
                content_type or "no content type",
            )
            raise UnauthorizedError("userinfo lookup failed")
        return info

    async def _refresh_jwks(self) -> None:
        """Refresh the cached JWKS from the discovered ``jwks_uri``."""
        if not self._jwks_uri:
            raise RuntimeError("OIDCValidator used before bootstrap()")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self._jwks_uri)
            resp.raise_for_status()
            self._jwks = KeySet.import_key_set(resp.json())
            self._jwks_fetched_at = time.monotonic()

    async def _jwks_or_refresh(self) -> KeySet:
        """Return the cached JWKS, refreshing it if past the TTL."""
        if (
            self._jwks is None
            or (time.monotonic() - self._jwks_fetched_at)
            >= self._settings.jwks_cache_ttl
        ):
            await self._refresh_jwks()
        if self._jwks is None:
            raise RuntimeError("JWKS refresh did not populate cache")
        return self._jwks

    async def validate(self, token: str) -> dict[str, Any]:
        """Validate ``token`` and return its claims.

        Raises :class:`UnauthorizedError` for any cryptographic or
        claim-shape failure, and :class:`ForbiddenError` when required
        scopes are missing.
        """
        jwks = await self._jwks_or_refresh()
        try:
            decoded = jwt.decode(token, key=jwks, algorithms=self._algorithms)
            claims = decoded.claims
            registry = JWTClaimsRegistry(
                iss={
                    "essential": True,
                    "value": self._issuer_from_discovery or self._settings.issuer,
                },
                aud={"essential": True, "value": self._settings.audience},
                exp={"essential": True},
                leeway=self._settings.clock_skew,
            )
            registry.validate(claims)
        except JoseError as exc:
            logger.warning("JWT validation failed: %s", exc)
            raise UnauthorizedError("invalid token") from exc

        self._enforce_scopes(claims)
        return dict(claims)

    def _enforce_scopes(self, claims: dict[str, Any]) -> None:
        """Reject if any configured ``required_scopes`` is absent."""
        required = self._settings.required_scopes
        if not required:
            return
        raw = claims.get("scope") or claims.get("scp") or ""
        present = set(raw) if isinstance(raw, list) else set(str(raw).split())
        missing = [s for s in required if s not in present]
        if missing:
            raise ForbiddenError(
                "token missing required scope(s): " + ", ".join(missing)
            )

    def principal_from(
        self, claims: dict[str, Any], userinfo: dict[str, Any] | None = None
    ) -> Principal:
        """Project validated claims into a :class:`Principal`.

        ``principal_claim`` may be a dotted path (e.g. ``ctx.group_id``)
        to pull an identifier out of a nested claim object. Each segment
        must resolve to a dict until the final segment, which must
        resolve to a non-empty string.
        """
        path = self._settings.principal_claim
        value = _walk_claim_path(claims, path)
        if not isinstance(value, str) or not value:
            raise UnauthorizedError(f"token missing or non-string claim {path!r}")
        return Principal(id=value, claims=claims, userinfo=userinfo or {})


def _walk_claim_path(claims: dict[str, Any], path: str) -> Any:
    """Resolve a claim name or dotted ``path`` like ``ctx.group_id``.

    An exact top-level name wins over the dotted path, so URI-named
    claims such as ``https://example.org/groups`` resolve. Returns
    ``None`` if any intermediate segment is missing or not a dict.
    """
    if path in claims or "." not in path:
        return claims.get(path)
    current: Any = claims
    for segment in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _extract_bearer(request: Request) -> str:
    """Pull the bearer token from the ``Authorization`` header."""
    header = request.headers.get("authorization") or request.headers.get(
        "Authorization"
    )
    if not header or not header.startswith(_BEARER_PREFIX):
        raise UnauthorizedError("missing bearer token")
    return header[len(_BEARER_PREFIX) :].strip()


async def get_principal(request: Request) -> Principal:
    """FastAPI dependency: validate the request's JWT and return the principal.

    When auth is disabled (``app.state.oidc is None``) every request is
    served as a fixed anonymous principal so downstream code paths stay
    uniform — the principal column is still stamped, just with a
    sentinel value.
    """
    validator: OIDCValidator | None = getattr(request.app.state, "oidc", None)
    if validator is None:
        return Principal(id=ANONYMOUS_PRINCIPAL_ID, claims={})
    token = _extract_bearer(request)
    claims = await validator.validate(token)
    userinfo = (
        await validator.userinfo(token, claims) if validator.userinfo_enabled else None
    )
    return validator.principal_from(claims, userinfo)
