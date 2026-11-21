"""API key persistence: free functions over an asyncpg connection.

Only the SHA-256 of a key is stored (``key_hash``); see
`poiesis.api.apikey_auth` for the key format and how keys authenticate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping, Sequence
    from datetime import datetime, timedelta

    import asyncpg


@dataclass(slots=True, frozen=True)
class ApiKeyRecord:
    """An API key as its owner sees it: everything but the hash."""

    id: uuid.UUID
    name: str
    scopes: tuple[str, ...]
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class ApiKeyCredential:
    """What authenticating with a key needs: owner, scopes, snapshot, state."""

    id: uuid.UUID
    owner: str
    scopes: tuple[str, ...]
    claims_snapshot: dict[str, Any] = field(default_factory=dict)
    revoked: bool = False
    expired: bool = False
    # When the key was minted, which is also when its snapshot was taken.
    created_at: datetime | None = None


async def create_api_key(  # noqa: PLR0913 (one column per argument)
    conn: asyncpg.Connection,
    *,
    key_id: uuid.UUID,
    name: str,
    key_hash: bytes,
    owner: str,
    scopes: Sequence[str],
    claims_snapshot: Mapping[str, Any],
    ttl: timedelta,
    max_active: int,
    lock_timeout_ms: int = 5000,
) -> ApiKeyRecord | None:
    """Insert a key that expires ``ttl`` from now; ``None`` if over the cap.

    The cap counts the owner's active keys (not revoked, not expired).
    A transaction-scoped advisory lock per owner serialises concurrent
    mints of one owner, so two requests can't both see room for the
    last key; other owners don't wait (unless their hashes collide).
    Waiting for it is bounded by ``lock_timeout_ms``: past that,
    ``asyncpg.LockNotAvailableError`` (a retryable ``503`` upstream).
    "Now" is the wall clock (``clock_timestamp()``), not the start of
    the transaction, so time spent waiting for the lock neither counts
    a key that has expired meanwhile nor shortens the new key's life.
    """
    async with conn.transaction():
        # Like SET LOCAL (ends with the transaction), but with a parameter.
        await conn.execute(
            "SELECT set_config('lock_timeout', $1, true)", f"{int(lock_timeout_ms)}ms"
        )
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('poiesis.api_keys'), hashtext($1))",
            owner,
        )
        active = await conn.fetchval(
            """
            SELECT count(*) FROM api_keys
            WHERE owner = $1
                AND revoked_at IS NULL
                AND expires_at > clock_timestamp()
            """,
            owner,
        )
        if active >= max_active:
            return None
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (
                id, name, key_hash, owner, scopes, claims_snapshot, expires_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6::jsonb, clock_timestamp() + $7::interval
            )
            RETURNING created_at, expires_at
            """,
            key_id,
            name,
            key_hash,
            owner,
            list(scopes),
            json.dumps(claims_snapshot),
            ttl,
        )
    assert row is not None  # INSERT ... RETURNING always returns the row
    return ApiKeyRecord(
        id=key_id,
        name=name,
        scopes=tuple(scopes),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


async def find_api_key(
    conn: asyncpg.Connection, key_hash: bytes
) -> ApiKeyCredential | None:
    """Return the key with hash ``key_hash``, with its state; ``None`` if none.

    Revoked and expired keys are returned too (flagged), so the caller
    can log why a key was refused; the database clock decides expiry,
    as it set ``expires_at``. The lookup compares hashes only: timing
    can at most reveal a prefix of a key's SHA-256, which doesn't help
    to find the key, so no constant-time comparison is needed on top.
    """
    row = await conn.fetchrow(
        """
        SELECT
            id, owner, scopes, claims_snapshot, created_at,
            revoked_at IS NOT NULL AS revoked,
            expires_at <= now() AS expired
        FROM api_keys
        WHERE key_hash = $1
        """,
        key_hash,
    )
    if row is None:
        return None
    snapshot = row["claims_snapshot"]
    snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
    return ApiKeyCredential(
        id=row["id"],
        owner=row["owner"],
        scopes=tuple(row["scopes"]),
        claims_snapshot=snapshot if isinstance(snapshot, dict) else {},
        revoked=row["revoked"],
        expired=row["expired"],
        created_at=row["created_at"],
    )


async def list_api_keys(conn: asyncpg.Connection, owner: str) -> list[ApiKeyRecord]:
    """Return every key of ``owner``, revoked and expired ones too, newest first."""
    rows = await conn.fetch(
        """
        SELECT id, name, scopes, created_at, expires_at, last_used_at, revoked_at
        FROM api_keys
        WHERE owner = $1
        ORDER BY created_at DESC, id
        """,
        owner,
    )
    return [
        ApiKeyRecord(
            id=row["id"],
            name=row["name"],
            scopes=tuple(row["scopes"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            last_used_at=row["last_used_at"],
            revoked_at=row["revoked_at"],
        )
        for row in rows
    ]


async def revoke_api_key(
    conn: asyncpg.Connection, key_id: uuid.UUID, owner: str
) -> bool:
    """Revoke key ``key_id`` of ``owner``; ``False`` if ``owner`` has no such key.

    Revoking a revoked key keeps its first ``revoked_at`` and succeeds.
    """
    revoked = await conn.fetchval(
        """
        UPDATE api_keys SET revoked_at = coalesce(revoked_at, now())
        WHERE id = $1 AND owner = $2
        RETURNING id
        """,
        key_id,
        owner,
    )
    return revoked is not None


async def touch_api_keys(
    conn: asyncpg.Connection, used: Mapping[uuid.UUID, datetime]
) -> None:
    """Record when keys were last used, in one statement.

    Never moves ``last_used_at`` back, so replicas flushing out of order
    (or a retried, older batch) can't overwrite a newer time.
    """
    if not used:
        return
    await conn.execute(
        """
        UPDATE api_keys AS k
        SET last_used_at = greatest(k.last_used_at, u.used_at)
        FROM unnest($1::uuid[], $2::timestamptz[]) AS u (id, used_at)
        WHERE k.id = u.id
        """,
        list(used),
        list(used.values()),
    )
