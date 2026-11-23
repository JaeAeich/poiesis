"""JWT authentication against a fixed list of trusted issuers.

:class:`JWTAuthenticator` is the chain's authenticator for signed JWTs
(``Authorization: Bearer <jwt>``). The token's unverified ``iss`` only
selects one of the configured issuers (exact match); keys are fetched
from that issuer's discovery document or static ``jwksUri``, never from
a URL taken from the token. The token is then verified in full: the
signature, ``iss``, ``aud`` (any of the issuer's audiences), ``exp``,
the header ``typ`` (access tokens only, ``tokenTypes``), the client
(``clients``, if set) and the issuer's required scopes. The owner of
its principal is ``<namespace>|<subject>``, with the issuer's
``namespace`` (default: the issuer).

Each configured issuer is an :class:`IssuerValidator`, which is
resilient to its issuer being down:

- At startup a first bootstrap (discovery, JWKS) is tried. If the
    issuer is unreachable the API starts anyway; a background task
    retries (1 s, doubling, at most 30 s apart) and the issuer's tokens
    get ``503`` with ``Retry-After`` until it succeeds. A
    misconfiguration (the discovery document names another issuer, has
    no usable ``jwks_uri`` or ``userinfo_endpoint``, the JWKS is
    unusable, a ``4xx`` answer) fails the start; found later by the
    background task, it is logged as an error and the issuer stays
    unready.
- When the cached key set expires and can't be refreshed, the stale
    keys keep serving (with a warning) and the refresh is retried after
    a back-off rather than on every request. Without any key set,
    ``503``.
- A token signed with an unknown ``kid`` (key rotation) refetches the
    JWKS once, at most every 30 s per issuer; still unknown, ``401``.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import copy
import dataclasses
import hashlib
import json
import logging
import math
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from poiesis.api.auth import Actor, Principal, client_of, walk_claim_path
from poiesis.api.exceptions import (
    InsufficientScopeError,
    ServiceUnavailableError,
    UnauthorizedError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi import Request

    from poiesis.api.settings import IssuerSettings, ServiceClientSettings

logger = logging.getLogger(__name__)

_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"
#: Userinfo responses are cached per token until the token expires, but
#: at most this many seconds (bounds the lag after a revocation) ...
_USERINFO_MAX_AGE = 300.0
#: ... and for at most this many tokens; the least recently used go first.
_USERINFO_CACHE_SIZE = 4096
#: ``Retry-After`` seconds advertised when the issuer can't be reached.
_ISSUER_RETRY_AFTER = 5
#: First and longest wait (seconds) between failed bootstraps or refreshes.
_RETRY_INITIAL = 1.0
_RETRY_MAX = 30.0
#: At most one JWKS refetch for an unknown ``kid`` per this many seconds.
_KID_REFETCH_INTERVAL = 30.0
#: ``Retry-After``-worthy statuses; other non-200 answers are misconfiguration.
_RETRYABLE_STATUSES = frozenset({408, 429})
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


def _monotonic() -> float:
    """Return the monotonic clock (a seam for tests)."""
    return time.monotonic()


def _backoff(failures: int) -> float:
    """Seconds to wait after ``failures`` consecutive failures (>= 1)."""
    return min(_RETRY_INITIAL * 2 ** (failures - 1), _RETRY_MAX)


def _unavailable() -> ServiceUnavailableError:
    """The ``503`` for an issuer that can't be reached."""
    return ServiceUnavailableError(
        "identity provider unavailable", retry_after_seconds=_ISSUER_RETRY_AFTER
    )


class IssuerConfigError(RuntimeError):
    """The issuer's answers show a misconfiguration; retrying won't help."""


class IssuerUnavailableError(Exception):
    """The issuer can't be reached right now (transport, timeout, 5xx)."""


class IssuerValidator:
    """Validates JWTs of one configured issuer; caches its keys.

    One HTTP client per validator keeps connections to the issuer alive
    across discovery, JWKS and userinfo calls.
    """

    def __init__(self, settings: IssuerSettings) -> None:
        """Capture settings; network calls start in :meth:`start`."""
        self.settings = settings
        self._jwks_uri: str | None = settings.jwks_uri
        self._userinfo_uri: str | None = None
        self._userinfo_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = (
            OrderedDict()
        )
        self._keys: KeySet | None = None
        self._kids: frozenset[str] = frozenset()
        self._fetched_at = -math.inf
        # Consecutive failed refreshes, and no refresh before _retry_at.
        self._failures = 0
        self._retry_at = -math.inf
        self._kid_refetch_at = -math.inf
        # Bumped by every refresh attempt, so waiters skip a repeat.
        self._attempts = 0
        self._lock = asyncio.Lock()
        self._retry_task: asyncio.Task[None] | None = None
        self._algorithms = list(_DEFAULT_ALGORITHMS)
        self._token_types = frozenset(
            normalize_token_type(typ) for typ in settings.token_types
        )
        self._client: httpx.AsyncClient | None = None

    @property
    def ready(self) -> bool:
        """Whether a key set is loaded, so tokens can be validated."""
        return self._keys is not None

    @property
    def userinfo_enabled(self) -> bool:
        """Whether principals carry the issuer's userinfo response."""
        return self._userinfo_uri is not None

    def _http(self) -> httpx.AsyncClient:
        """Return the validator's HTTP client, creating it on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.settings.timeout)
        return self._client

    async def start(self) -> None:
        """Bootstrap once; if the issuer is down, retry in the background.

        :class:`IssuerConfigError` propagates so the start fails loudly.
        """
        try:
            await self._bootstrap()
        except IssuerUnavailableError as exc:
            logger.warning(
                "Issuer %s unavailable at startup (%s); retrying in the "
                "background, its tokens get 503 until then",
                self.settings.issuer,
                exc,
            )
            self._retry_task = asyncio.create_task(self._retry_bootstrap())

    async def aclose(self) -> None:
        """Stop the background retry and close the HTTP client."""
        if self._retry_task is not None:
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task
            self._retry_task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _retry_bootstrap(self) -> None:
        """Retry the bootstrap with back-off until it succeeds."""
        failures = 1
        while True:
            await asyncio.sleep(_backoff(failures))
            try:
                await self._bootstrap()
            except IssuerConfigError as exc:
                logger.error(
                    "Issuer %s is misconfigured: %s", self.settings.issuer, exc
                )
            except IssuerUnavailableError as exc:
                logger.warning(
                    "Issuer %s still unavailable (%s)", self.settings.issuer, exc
                )
            else:
                return
            failures += 1

    async def _bootstrap(self) -> None:
        """Discover the endpoints (unless ``jwksUri`` is set); load keys."""
        if self.settings.jwks_uri is None:
            await self._discover()
        self._store_keys(await self._fetch_keys())
        logger.info(
            "Issuer %s ready: jwks_uri=%s", self.settings.issuer, self._jwks_uri
        )

    async def _discover(self) -> None:
        """Fetch the discovery document; its ``issuer`` must be ours."""
        issuer = self.settings.issuer
        doc = await self._get_json(
            issuer.rstrip("/") + _DISCOVERY_SUFFIX, "discovery document"
        )
        if not isinstance(doc, dict):
            raise IssuerConfigError(f"discovery document of {issuer} isn't an object")
        if doc.get("issuer") != issuer:
            raise IssuerConfigError(
                f"discovery document names issuer {doc.get('issuer')!r}, not the "
                f"configured {issuer!r}; the configured issuer must match exactly"
            )
        jwks_uri = self._checked_uri(doc.get("jwks_uri"), "jwks_uri")
        userinfo_uri = None
        if self.settings.userinfo.enabled:
            userinfo_uri = self._checked_uri(
                doc.get("userinfo_endpoint"), "userinfo_endpoint"
            )
        self._jwks_uri, self._userinfo_uri = jwks_uri, userinfo_uri

    def _checked_uri(self, uri: Any, name: str) -> str:
        """Return the discovered endpoint ``name`` if it is safe to use.

        It must be an absolute ``https`` URL, or ``http`` if the issuer
        is ``http`` too (e.g. a development IdP), so that keys and tokens
        never travel less protected than the operator chose for the
        issuer.
        """
        parts = urlsplit(uri) if isinstance(uri, str) else None
        allowed = {"https", urlsplit(self.settings.issuer).scheme}
        if parts is None or parts.scheme not in allowed or not parts.netloc:
            raise IssuerConfigError(
                f"the discovery document of {self.settings.issuer} has no usable {name}"
            )
        return uri

    async def _get_json(self, url: str, what: str) -> Any:
        """GET JSON from the issuer; classify failures as outage or config."""
        try:
            resp = await _get(url, self.settings.timeout, client=self._http())
        except (httpx.HTTPError, TimeoutError) as exc:
            raise IssuerUnavailableError(f"{what}: {type(exc).__name__}") from exc
        status = resp.status_code
        if status >= httpx.codes.INTERNAL_SERVER_ERROR or status in (
            _RETRYABLE_STATUSES
        ):
            raise IssuerUnavailableError(f"{what}: status {status}")
        if status != httpx.codes.OK:
            raise IssuerConfigError(f"{what} at {url} answered {status}")
        try:
            return resp.json()
        except ValueError as exc:
            raise IssuerConfigError(f"{what} at {url} is not JSON") from exc

    async def _fetch_keys(self) -> KeySet:
        """Fetch and parse the key set at the JWKS URL."""
        if self._jwks_uri is None:
            raise RuntimeError("IssuerValidator: no JWKS URL before discovery")
        doc = await self._get_json(self._jwks_uri, "JWKS")
        try:
            return KeySet.import_key_set(doc)
        except (JoseError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise IssuerConfigError(
                f"JWKS at {self._jwks_uri} is not a usable key set: {exc}"
            ) from exc

    def _store_keys(self, keys: KeySet) -> None:
        """Cache a freshly fetched key set."""
        self._keys = keys
        self._kids = frozenset(key.kid for key in keys if key.kid)
        self._fetched_at = _monotonic()
        self._failures = 0
        self._retry_at = -math.inf

    async def _keys_for(self, kid: str | None) -> KeySet:
        """Return the key set for a token with ``kid``, refreshing if due."""
        keys = self._keys
        if keys is None:
            raise _unavailable()
        now = _monotonic()
        unknown = kid is not None and kid not in self._kids
        if unknown and now - self._kid_refetch_at >= _KID_REFETCH_INTERVAL:
            self._kid_refetch_at = now
            await self._refresh(f"unknown kid {kid[:64]!r}")
        elif (
            now - self._fetched_at >= self.settings.jwks_cache_ttl
            and now >= self._retry_at
        ):
            await self._refresh("cache expired")
        return self._keys or keys

    async def _refresh(self, reason: str) -> None:
        """Refetch the key set; on failure keep the cached one and back off."""
        seen = self._attempts
        async with self._lock:
            if self._attempts != seen:  # refreshed while we waited
                return
            self._attempts += 1
            try:
                keys = await self._fetch_keys()
            except (IssuerConfigError, IssuerUnavailableError) as exc:
                self._failures += 1
                delay = _backoff(self._failures)
                self._retry_at = _monotonic() + delay
                logger.warning(
                    "JWKS refresh for %s (%s) failed: %s; keeping the cached "
                    "keys, next try in %.0f s",
                    self.settings.issuer,
                    reason,
                    exc,
                    delay,
                )
                return
            self._store_keys(keys)

    async def authenticate(self, token: str, kid: str | None) -> Principal:
        """Validate ``token`` (header ``kid``) and return its principal.

        Raises :class:`UnauthorizedError` for any cryptographic or claim
        failure, a token type or client that isn't accepted,
        :class:`InsufficientScopeError` when required scopes are
        missing, and :class:`ServiceUnavailableError` while the issuer
        has no key set yet.
        """
        keys = await self._keys_for(kid)
        try:
            decoded = jwt.decode(token, key=keys, algorithms=self._algorithms)
            claims = dict(decoded.claims)
            # Signed by the issuer: a service client's own token gets that
            # client's audience instead of the issuer's (users').
            service = self._service_client(claims)
            audience = self.settings.audience if service is None else service.audience
            JWTClaimsRegistry(
                iss={"essential": True, "value": self.settings.issuer},
                aud={"essential": True, "values": list(audience)},
                exp={"essential": True},
                leeway=self.settings.clock_skew,
            ).validate(claims)
        except (JoseError, ValueError) as exc:
            logger.warning(
                "JWT validation failed for %s: %s", self.settings.issuer, exc
            )
            raise UnauthorizedError("invalid token") from exc
        # After the signature: only the issuer's own header and claims count.
        self._check_token_type(decoded.header.get("typ"))
        if service is None:
            # `clients` lists the user-facing clients; service clients
            # are listed on their own.
            self._check_client(claims)

        scopes = _scopes(claims)
        missing = [s for s in self.settings.required_scopes if s not in scopes]
        if missing:
            raise InsufficientScopeError(
                "token missing required scope(s): " + ", ".join(missing),
                self.settings.required_scopes,
            )
        # Resolve the owner first so a token without it never reaches userinfo.
        principal = self.principal_from(claims, scopes)
        if service is not None:
            # No user behind the token: nothing to look up at userinfo.
            return dataclasses.replace(principal, service_client=True)
        if self._userinfo_uri is not None:
            userinfo = await self.userinfo(token, claims)
            principal = dataclasses.replace(principal, userinfo=userinfo)
        return principal

    def _service_client(self, claims: dict[str, Any]) -> ServiceClientSettings | None:
        """Return the service client whose own token ``claims`` are, if any.

        The token's client (``azp``, else ``client_id``) must be listed
        in ``serviceClients`` and ``sub`` must equal it, as in tokens of
        the client credentials grant; a user token through that client
        carries the user's ``sub`` and so never matches.
        """
        client = client_of(claims)
        if not isinstance(client, str) or claims.get("sub") != client:
            return None
        return self.settings.service_client(client)

    def _check_token_type(self, typ: Any) -> None:
        """Raise ``401`` unless the header ``typ`` is one of ``tokenTypes``.

        An empty ``tokenTypes`` accepts any (or no) ``typ``. The issuer's
        ID tokens and other JWTs carry another ``typ`` than its access
        tokens (RFC 9068's ``at+jwt``) at IdPs that set it; at those
        that don't, the operator lists what their access tokens carry.
        """
        if not self._token_types:
            return
        if isinstance(typ, str) and normalize_token_type(typ) in self._token_types:
            return
        # semgrep false positive: logs the issuer and a truncated header
        # value, never the token.
        logger.warning(  # nosemgrep
            "Token of %s refused: header typ %s is not in its tokenTypes %s; if "
            "the issuer's access tokens carry it, add it to "
            "auth.issuers[].tokenTypes",
            self.settings.issuer,
            "missing" if typ is None else repr(str(typ)[:64]),
            list(self.settings.token_types),
        )
        raise UnauthorizedError("invalid token")

    def _check_client(self, claims: dict[str, Any]) -> None:
        """Raise ``401`` unless the token's client is in ``clients`` (if set)."""
        allowed = self.settings.clients
        if allowed is None:
            return
        client = client_of(claims)
        if isinstance(client, str) and client in allowed:
            return
        # semgrep false positive: logs the issuer and a truncated client
        # id, never the token.
        logger.warning(  # nosemgrep
            "Token of %s refused: client %s is not in its clients",
            self.settings.issuer,
            "missing" if client is None else repr(str(client)[:100]),
        )
        raise UnauthorizedError("invalid token")

    def principal_from(
        self, claims: dict[str, Any], scopes: frozenset[str] = frozenset()
    ) -> Principal:
        """Project validated claims into a :class:`Principal`.

        ``principalClaim`` may be a dotted path (e.g. ``ctx.group_id``)
        to pull an identifier out of a nested claim object; it must
        resolve to a non-empty string.
        """
        path = self.settings.principal_claim
        subject = walk_claim_path(claims, path)
        if not isinstance(subject, str) or not subject:
            raise UnauthorizedError(f"token missing or non-string claim {path!r}")
        jti = claims.get("jti")
        return Principal(
            issuer=self.settings.issuer,
            subject=subject,
            via="oidc",
            namespace=self.settings.owner_namespace,
            credential_id=jti if isinstance(jti, str) and jti else None,
            actor=_actor(claims, self.settings.issuer, self.settings.actors),
            scopes=scopes,
            claims=claims,
        )

    async def userinfo(self, token: str, claims: dict[str, Any]) -> dict[str, Any]:
        """Return the userinfo response for a validated token.

        Cached per token (by hash) until the token expires, at most
        ``_USERINFO_MAX_AGE`` seconds; concurrent first requests with one
        token may each fetch. Fails closed: a refused token, a non-JSON
        answer or a ``sub`` that differs from the token's raises
        :class:`UnauthorizedError`; an issuer that can't be reached, is
        too slow or answers 5xx raises :class:`ServiceUnavailableError`,
        so an IdP outage doesn't look like a bad token to clients.
        """
        if self._userinfo_uri is None:
            raise RuntimeError("userinfo lookup is not enabled")
        key = hashlib.sha256(token.encode()).hexdigest()
        now = time.time()
        cached = self._userinfo_cache.get(key)
        if cached is not None and cached[0] > now:
            self._userinfo_cache.move_to_end(key)
            return copy.deepcopy(cached[1])

        info = await self._fetch_userinfo(
            self._userinfo_uri, token, self.settings.timeout, client=self._http()
        )
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
        return copy.deepcopy(info)

    @staticmethod
    async def _fetch_userinfo(
        uri: str,
        token: str,
        timeout: float,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """GET userinfo at ``uri`` with ``token``.

        An outage (transport error, timeout, 5xx) is a 503; any other
        failure is a 401. Only plain JSON is accepted: signed or
        encrypted userinfo (``application/jwt``) is not supported.
        """
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        try:
            resp = await _get(uri, timeout, headers, client=client)
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("Userinfo request failed: %s", type(exc).__name__)
            raise _unavailable() from exc
        if resp.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            logger.warning("Userinfo endpoint answered %s", resp.status_code)
            raise _unavailable()
        content_type = resp.headers.get("content-type", "")
        info: Any = None
        media_type = content_type.split(";")[0].strip().lower()
        if resp.status_code == httpx.codes.OK and media_type == "application/json":
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


class JWTAuthenticator:
    """The chain's authenticator for bearer JWTs of the configured issuers."""

    name = "jwt"

    def __init__(self, issuers: Sequence[IssuerSettings]) -> None:
        """Build one validator per issuer; nothing is fetched yet."""
        self.issuers = {entry.issuer: IssuerValidator(entry) for entry in issuers}

    async def start(self) -> None:
        """Bootstrap every issuer concurrently; a misconfiguration raises."""
        try:
            async with asyncio.TaskGroup() as group:
                for validator in self.issuers.values():
                    group.create_task(validator.start())
        except ExceptionGroup as exc:
            raise exc.exceptions[0]  # noqa: B904 (the group adds nothing)

    async def aclose(self) -> None:
        """Close every issuer's client and background task."""
        for validator in self.issuers.values():
            await validator.aclose()

    async def authenticate(self, request: Request) -> Principal | None:
        """Validate a bearer JWT; ``None`` if the credential isn't one.

        Only a JWS compact token (three dot-separated parts) is taken;
        anything else is left to the next authenticator. Its unverified
        ``iss`` must name a configured issuer exactly, else ``401``.
        """
        token = _bearer_jwt(request.headers.get("authorization"))
        if token is None:
            return None
        header_segment, payload_segment, _ = token.split(".")
        header = _segment_json(header_segment)
        issuer = _segment_json(payload_segment).get("iss")
        validator = self.issuers.get(issuer) if isinstance(issuer, str) else None
        if validator is None:
            logger.warning("Token from an unconfigured issuer %r", str(issuer)[:200])
            raise UnauthorizedError("invalid token")
        kid = header.get("kid")
        return await validator.authenticate(
            token, kid if isinstance(kid, str) else None
        )


def normalize_token_type(value: str) -> str:
    """Return the comparable form of a JWT ``typ`` header value.

    Media types compare case-insensitively, and ``typ`` may leave out
    the ``application/`` prefix (RFC 7515, section 4.1.9), so
    ``application/at+jwt`` and ``AT+JWT`` both become ``at+jwt``.
    """
    return value.strip().lower().removeprefix("application/")


def _bearer_jwt(header: str | None) -> str | None:
    """Return the token of a ``Bearer`` header if it is JWT-shaped."""
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or token.count(".") != 2:  # noqa: PLR2004
        return None
    return token


def _segment_json(segment: str) -> dict[str, Any]:
    """Decode an unverified base64url JSON object, or raise ``401``."""
    try:
        value = json.loads(
            base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        )
    except ValueError as exc:
        raise UnauthorizedError("invalid token") from exc
    if not isinstance(value, dict):
        raise UnauthorizedError("invalid token")
    return value


def _scopes(claims: dict[str, Any]) -> frozenset[str]:
    """Return the token's scopes, from ``scope`` or else ``scp``."""
    raw = claims.get("scope")
    if raw is None:
        raw = claims.get("scp")
    if isinstance(raw, str):
        return frozenset(raw.split())
    if isinstance(raw, list):
        return frozenset(s for s in raw if isinstance(s, str))
    return frozenset()


def _actor(
    claims: dict[str, Any], issuer: str, listed: Sequence[str] = ()
) -> Actor | None:
    """Return the RFC 8693 ``act`` claim's actor; nested chains are ignored.

    The actor is ``listed`` if its ``sub`` is in ``listed`` (the token
    issuer's ``actors``) and it is of the token's own issuer: an actor
    id of another issuer may name someone else. A malformed ``act``
    (not an object, no string ``sub``, a non-string ``iss``) is a
    ``401``: delegation must not be guessed.
    """
    act = claims.get("act")
    if act is None:
        return None
    sub = act.get("sub") if isinstance(act, dict) else None
    iss = act.get("iss", issuer) if isinstance(act, dict) else None
    if not (isinstance(sub, str) and sub and isinstance(iss, str) and iss):
        logger.warning("Token with a malformed act claim")
        raise UnauthorizedError("invalid token")
    return Actor(issuer=iss, subject=sub, listed=iss == issuer and sub in listed)


async def _get(
    url: str,
    timeout: float,
    headers: dict[str, str] | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """GET ``url`` from the issuer within ``timeout`` seconds in total.

    httpx's own timeout applies to each connect or read separately, so
    a slowly trickling answer could take far longer; the overall
    deadline raises :class:`TimeoutError`. Uses ``client`` when given
    (the validator's shared client), else a short-lived one.
    """
    async with asyncio.timeout(timeout):
        if client is not None:
            return await client.get(url, headers=headers)
        async with httpx.AsyncClient(timeout=timeout) as own:
            return await own.get(url, headers=headers)
