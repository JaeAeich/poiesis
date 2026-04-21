"""Database pool lifecycle.

One place that knows asyncpg. App startup constructs a pool via
`create_pool(dsn)` and passes it (or acquired connections) to the
free functions in sibling modules.
"""

from __future__ import annotations

import asyncpg


async def create_pool(
    dsn: str, *, min_size: int = 1, max_size: int = 10
) -> asyncpg.Pool:
    """Open a connection pool against the given DSN.

    Schema migrations are applied out-of-band by `golang-migrate/migrate`
    against `./migrations/`, typically by an init container before the API
    replicas start. This factory does not run DDL.
    """
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
