"""SQL tests for `poiesis.db.api_keys` against a real Postgres.

They run when ``POIESIS_TEST_DATABASE_URL`` names a database (CI starts
a Postgres service for them) and are skipped otherwise. Each test
applies the migrations in a schema of its own and drops it afterwards,
so tests don't see each other's rows.
"""

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from poiesis.db import api_keys as api_keys_db

DSN = os.environ.get("POIESIS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DSN, reason="POIESIS_TEST_DATABASE_URL not set")
MIGRATIONS = sorted((Path(__file__).parents[2] / "migrations").glob("*.up.sql"))
ALICE = "https://kc.example.org/realms/poiesis|alice"
BOB = "https://kc.example.org/realms/poiesis|bob"


def run(test: Callable[[Any], Awaitable[None]], pool_size: int = 25) -> None:
    """Run ``test(pool)`` against a freshly migrated, private schema."""

    async def main() -> None:
        schema = f"test_{uuid.uuid4().hex}"
        admin = await asyncpg.connect(DSN)
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        try:
            pool = await asyncpg.create_pool(
                DSN,
                min_size=1,
                max_size=pool_size,
                server_settings={"search_path": schema},
            )
            try:
                async with pool.acquire() as conn:
                    for migration in MIGRATIONS:
                        await conn.execute(migration.read_text())
                await test(pool)
            finally:
                await pool.close()
        finally:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
            await admin.close()

    asyncio.run(main())


async def mint(
    pool: Any, owner: str = ALICE, max_active: int = 5, **kwargs: Any
) -> api_keys_db.ApiKeyRecord | None:
    """Mint a key with a random hash on a connection of its own."""
    async with pool.acquire() as conn:
        return await api_keys_db.create_api_key(
            conn,
            key_id=uuid.uuid4(),
            name="k",
            key_hash=os.urandom(32),
            owner=owner,
            scopes=["tasks:read"],
            claims_snapshot={"claims": {"sub": "alice"}},
            ttl=kwargs.pop("ttl", timedelta(days=1)),
            max_active=max_active,
            **kwargs,
        )


def test_cap_counts_active_keys() -> None:
    """The cap refuses a key over it; revoking one makes room again."""

    async def test(pool: Any) -> None:
        first = await mint(pool, max_active=2)
        assert first is not None
        assert await mint(pool, max_active=2) is not None
        assert await mint(pool, max_active=2) is None
        assert await mint(pool, owner=BOB, max_active=2) is not None
        async with pool.acquire() as conn:
            assert await api_keys_db.revoke_api_key(conn, first.id, ALICE)
        assert await mint(pool, max_active=2) is not None

    run(test)


def test_concurrent_mints_respect_cap() -> None:
    """20 simultaneous mints against a cap of 5 create exactly 5 keys."""

    async def test(pool: Any) -> None:
        results = await asyncio.gather(*(mint(pool) for _ in range(20)))
        assert sum(r is not None for r in results) == 5  # noqa: PLR2004
        async with pool.acquire() as conn:
            listed = await api_keys_db.list_api_keys(conn, ALICE)
        assert len(listed) == 5  # noqa: PLR2004

    run(test)


def test_expired_keys_free_the_cap() -> None:
    """A key past its expiry no longer counts against the cap."""

    async def test(pool: Any) -> None:
        assert await mint(pool, max_active=1) is not None
        assert await mint(pool, max_active=1) is None
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE api_keys SET expires_at = clock_timestamp() - interval '1 s'"
            )
        assert await mint(pool, max_active=1) is not None

    run(test)


def test_expiry_is_ttl_from_now() -> None:
    """A key expires its TTL after it was minted."""

    async def test(pool: Any) -> None:
        before = datetime.now(UTC)
        record = await mint(pool, ttl=timedelta(hours=2))
        assert record is not None
        lifetime = record.expires_at - before
        assert timedelta(hours=2) <= lifetime < timedelta(hours=2, minutes=1)

    run(test)


def test_lock_wait_is_bounded() -> None:
    """A mint waiting on another mint of the same owner gives up in time."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as holder, holder.transaction():
            await holder.execute(
                "SELECT pg_advisory_xact_lock(hashtext('poiesis.api_keys'),"
                " hashtext($1))",
                ALICE,
            )
            # The outer timeout turns a regression (an unbounded wait) into
            # a failure instead of a hung test run.
            async with asyncio.timeout(5):
                with pytest.raises(asyncpg.LockNotAvailableError):
                    await mint(pool, lock_timeout_ms=100)
            # Other owners don't wait.
            assert await mint(pool, owner=BOB, lock_timeout_ms=100) is not None

    run(test)


def test_find_flags_revoked_and_expired() -> None:
    """Lookup by hash returns the key with its state; unknown hashes none."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            key_hash = os.urandom(32)
            record = await api_keys_db.create_api_key(
                conn,
                key_id=uuid.uuid4(),
                name="k",
                key_hash=key_hash,
                owner=ALICE,
                scopes=["tasks:read", "tasks:write"],
                claims_snapshot={"claims": {"groups": ["lab-alpha"]}},
                ttl=timedelta(days=1),
                max_active=5,
            )
            assert record is not None
            found = await api_keys_db.find_api_key(conn, key_hash)
            assert found is not None
            assert (found.owner, found.scopes) == (ALICE, ("tasks:read", "tasks:write"))
            assert found.claims_snapshot == {"claims": {"groups": ["lab-alpha"]}}
            assert not found.revoked
            assert not found.expired
            assert found.created_at == record.created_at
            assert await api_keys_db.find_api_key(conn, os.urandom(32)) is None

            await conn.execute(
                "UPDATE api_keys SET expires_at = clock_timestamp() - interval '1 s'"
            )
            expired = await api_keys_db.find_api_key(conn, key_hash)
            assert expired is not None
            assert expired.expired
            await api_keys_db.revoke_api_key(conn, record.id, ALICE)
            revoked = await api_keys_db.find_api_key(conn, key_hash)
            assert revoked is not None
            assert revoked.revoked

    run(test)


def test_revoke_own_keys_only() -> None:
    """Only the owner revokes a key; revoking twice keeps the first time."""

    async def test(pool: Any) -> None:
        record = await mint(pool)
        assert record is not None
        async with pool.acquire() as conn:
            assert not await api_keys_db.revoke_api_key(conn, record.id, BOB)
            assert await api_keys_db.revoke_api_key(conn, record.id, ALICE)
            first = await conn.fetchval("SELECT revoked_at FROM api_keys")
            assert await api_keys_db.revoke_api_key(conn, record.id, ALICE)
            assert await conn.fetchval("SELECT revoked_at FROM api_keys") == first

    run(test)


def test_touch_never_moves_back() -> None:
    """Recording use keeps the newest time, whatever order batches arrive in."""

    async def test(pool: Any) -> None:
        record = await mint(pool)
        assert record is not None
        newer = datetime.now(UTC)
        older = newer - timedelta(minutes=5)
        async with pool.acquire() as conn:
            await api_keys_db.touch_api_keys(conn, {record.id: newer})
            await api_keys_db.touch_api_keys(conn, {record.id: older})
            listed = await api_keys_db.list_api_keys(conn, ALICE)
        assert listed[0].last_used_at == newer

    run(test)
