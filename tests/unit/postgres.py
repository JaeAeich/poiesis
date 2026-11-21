"""A real Postgres for SQL tests, in a private schema per test.

The tests run when ``POIESIS_TEST_DATABASE_URL`` names a database (CI
starts a Postgres service for them) and are skipped otherwise: set
``pytestmark = needs_postgres`` in the test module. With
``POIESIS_TEST_REQUIRE_DATABASE=1`` (as in CI) a missing URL is an error
instead of a skip. Each test applies
the migrations in a schema of its own and drops it afterwards, so tests
don't see each other's rows.
"""

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import asyncpg
import pytest

DSN = os.environ.get("POIESIS_TEST_DATABASE_URL", "")
if not DSN and os.environ.get("POIESIS_TEST_REQUIRE_DATABASE") == "1":
    raise RuntimeError(
        "POIESIS_TEST_REQUIRE_DATABASE=1 but POIESIS_TEST_DATABASE_URL is not set"
    )
needs_postgres = pytest.mark.skipif(not DSN, reason="POIESIS_TEST_DATABASE_URL not set")
MIGRATIONS = sorted((Path(__file__).parents[2] / "migrations").glob("*.up.sql"))


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
