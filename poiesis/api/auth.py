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

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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
    downstream code (the future Authorizer) can inspect arbitrary
    fields without re-parsing the token.
    """

    id: str
    claims: dict[str, Any] = field(default_factory=dict)


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
        await self._refresh_jwks()
        logger.info(
            "OIDC discovery ok: issuer=%s jwks_uri=%s",
            self._issuer_from_discovery,
            self._jwks_uri,
        )

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

    def principal_from(self, claims: dict[str, Any]) -> Principal:
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
        return Principal(id=value, claims=claims)


def _walk_claim_path(claims: dict[str, Any], path: str) -> Any:
    """Resolve a dotted ``path`` like ``ctx.group_id`` against ``claims``.

    Returns ``None`` if any intermediate segment is missing or not a
    dict. The top-level case ``path='sub'`` is preserved for the common
    default with no dotted lookup overhead.
    """
    if "." not in path:
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
    return validator.principal_from(claims)
