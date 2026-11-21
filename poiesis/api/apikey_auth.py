"""API keys: long-lived credentials for clients that outlive a token.

Workflow engines read one credential at launch and poll for hours or
days, longer than any access token lives. An owner therefore mints a
Poiesis API key with an OIDC token (`poiesis.api.routes.api_keys`) and
hands the key to the engine. :class:`ApiKeyAuthenticator` is the chain's
link for those keys:

- A key is ``poi_``, 43 URL-safe base64 characters (32 random bytes)
    and a 6-character base62 CRC32 checksum of them, like GitHub's
    tokens: secret scanners can confirm a match offline, and a mistyped
    or made-up key is refused without a database lookup. It never
    contains a ``.``, so the JWT link, which takes any three-part bearer
    token, never claims one.
- Only its SHA-256 is stored; a request's key is looked up by hash on
    every request (no cache), so a revoked key stops working at once.
- Accepted as ``Authorization: Bearer poi_…`` and as HTTP Basic with
    any user name and the key as password (``user:poi_…``), for
    clients that only speak Basic.
- The principal is the minting owner (``issuer|subject``) with
    ``via="apikey"``, the key id as ``credential_id``, the key's scopes,
    and the claims and userinfo snapshot taken at minting, so the claim
    rule and decision service see what they saw for the owner's token.
    A key of an issuer that has since been removed from ``auth.issuers``
    no longer works.
- ``last_used_at`` is recorded in memory and written in one batch every
    minute and at shutdown, never once per request.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import logging
import re
import secrets
import string
import zlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import asyncpg

from poiesis.api.auth import Principal
from poiesis.api.exceptions import ServiceUnavailableError, UnauthorizedError
from poiesis.db import api_keys as api_keys_db

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable

    from fastapi import Request

logger = logging.getLogger(__name__)

KEY_PREFIX = "poi_"
#: Scopes a key may carry; ``tasks:write`` implies ``tasks:read``.
TASKS_READ = "tasks:read"
TASKS_WRITE = "tasks:write"
SCOPES: tuple[str, ...] = (TASKS_READ, TASKS_WRITE)
#: The shape of a key: the prefix, ``token_urlsafe(32)`` and a checksum.
_KEY = re.compile(r"poi_(?P<body>[A-Za-z0-9_-]{43})(?P<sum>[0-9A-Za-z]{6})")
_BASE62 = string.digits + string.ascii_letters
#: Base62 digits of a CRC32 (62**6 > 2**32).
_CHECKSUM_LENGTH = 6
#: Seconds between writes of the batched ``last_used_at`` times.
_FLUSH_INTERVAL = 60.0
#: ``Retry-After`` seconds advertised while the database can't be reached.
_DB_RETRY_AFTER = 5
#: Errors that mean the database is unavailable, not that the key is bad.
DB_ERRORS = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError)


def _checksum(body: str) -> str:
    """Return the base62 CRC32 of a key's random part, 6 characters."""
    value, digits = zlib.crc32(body.encode()), []
    for _ in range(_CHECKSUM_LENGTH):
        value, digit = divmod(value, len(_BASE62))
        digits.append(_BASE62[digit])
    return "".join(reversed(digits))


def new_key() -> str:
    """Return a fresh secret key: ``poi_``, 32 random bytes, a checksum."""
    body = secrets.token_urlsafe(32)
    return KEY_PREFIX + body + _checksum(body)


def well_formed(key: str) -> bool:
    """Whether ``key`` has a key's shape and a matching checksum.

    The checksum isn't secret: it catches typos, truncation and made-up
    strings, it doesn't authenticate anything.
    """
    match = _KEY.fullmatch(key)
    return match is not None and _checksum(match["body"]) == match["sum"]


def hash_key(key: str) -> bytes:
    """Return the stored form of ``key``: its SHA-256 digest."""
    return hashlib.sha256(key.encode()).digest()


def key_from_header(header: str | None) -> str | None:
    """Return the ``poi_`` credential of an ``Authorization`` header, if any.

    ``Bearer poi_…`` gives the token; ``Basic`` gives the password of
    the decoded ``user:password`` pair (the user name is ignored).
    Anything else, including a Basic password without the prefix, is
    ``None``: not an API key.
    """
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    scheme, value = scheme.lower(), value.strip()
    if scheme == "basic":
        try:
            pair = base64.b64decode(value, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            return None
        value = pair.partition(":")[2]
    elif scheme != "bearer":
        return None
    return value if value.startswith(KEY_PREFIX) else None


class ApiKeyAuthenticator:
    """The chain's authenticator for Poiesis API keys."""

    name = "apikey"

    def __init__(
        self,
        pool: Any,
        issuers: Iterable[str],
        *,
        flush_interval: float = _FLUSH_INTERVAL,
    ) -> None:
        """Keep the database pool and the issuers whose keys still count."""
        self._pool = pool
        self._issuers = frozenset(issuers)
        self._flush_interval = flush_interval
        self._used: dict[uuid.UUID, datetime] = {}
        self._flush_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start writing ``last_used_at`` in the background."""
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def aclose(self) -> None:
        """Stop the background writer and write what is left."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None
        await self.flush()

    async def authenticate(self, request: Request) -> Principal | None:
        """Return the key's principal; ``None`` if the credential isn't a key.

        A ``poi_`` credential that is malformed, unknown, revoked or
        expired, or whose owner's issuer is no longer configured, is a
        ``401``; a database outage is a ``503`` with ``Retry-After``.
        """
        key = key_from_header(request.headers.get("authorization"))
        if key is None:
            return None
        if not well_formed(key):
            logger.warning("Malformed API key")
            raise UnauthorizedError("invalid token")
        try:
            async with self._pool.acquire() as conn:
                record = await api_keys_db.find_api_key(conn, hash_key(key))
        except DB_ERRORS as exc:
            logger.warning("API key lookup failed: %s", type(exc).__name__)
            raise ServiceUnavailableError(
                "credential store unavailable", retry_after_seconds=_DB_RETRY_AFTER
            ) from exc
        if record is None:
            logger.warning("Unknown API key")
            raise UnauthorizedError("invalid token")
        issuer, _, subject = record.owner.partition("|")
        refusal = self._refusal(record, issuer, subject)
        if refusal is not None:
            logger.warning("API key %s refused: %s", record.id, refusal)
            raise UnauthorizedError("invalid token")
        self._used[record.id] = datetime.now(UTC)
        snapshot = record.claims_snapshot
        claims, userinfo = snapshot.get("claims"), snapshot.get("userinfo")
        return Principal(
            issuer=issuer,
            subject=subject,
            via="apikey",
            credential_id=str(record.id),
            scopes=frozenset(record.scopes),
            claims=claims if isinstance(claims, dict) else {},
            userinfo=userinfo if isinstance(userinfo, dict) else {},
        )

    def _refusal(
        self, record: api_keys_db.ApiKeyCredential, issuer: str, subject: str
    ) -> str | None:
        """Why a known key can't authenticate (for the log), or ``None``."""
        if record.revoked:
            return "revoked"
        if record.expired:
            return "expired"
        if issuer not in self._issuers or not subject:
            return f"issuer {issuer[:200]!r} is no longer configured"
        return None

    async def flush(self) -> None:
        """Write the pending ``last_used_at`` times in one statement.

        On a database error they are kept (newer uses win) and written
        with the next batch; usage times are best effort and never fail
        a request.
        """
        if not self._used:
            return
        batch, self._used = self._used, {}
        try:
            async with self._pool.acquire() as conn:
                await api_keys_db.touch_api_keys(conn, batch)
        except DB_ERRORS as exc:
            logger.warning(
                "Recording API key use failed (%s); retrying with the next batch",
                type(exc).__name__,
            )
            self._used = batch | self._used

    async def _flush_loop(self) -> None:
        """Flush every ``flush_interval`` seconds until cancelled."""
        while True:
            await asyncio.sleep(self._flush_interval)
            await self.flush()
