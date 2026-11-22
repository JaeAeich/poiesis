"""Database pool lifecycle.

One place that knows asyncpg. App startup constructs a pool via
`create_pool(dsn)` and passes it (or acquired connections) to the
free functions in sibling modules.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import asyncpg

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class PoolTimeoutError(TimeoutError):
    """No pooled connection became free within the acquire timeout."""


class Pool:
    """An asyncpg pool whose `acquire()` waits a bounded time.

    asyncpg's own `acquire()` waits forever by default, so a burst of
    requests behind a slow query queues without limit.
    """

    def __init__(self, pool: asyncpg.Pool, acquire_timeout: float) -> None:
        """Wrap `pool`; `acquire()` waits at most `acquire_timeout` seconds."""
        self._pool = pool
        self._acquire_timeout = acquire_timeout
        #: Callers waiting in `acquire()` for a connection.
        self._waiters = 0

    @contextlib.asynccontextmanager
    async def acquire(self, *, timeout: float | None = None) -> AsyncIterator[Any]:
        """Yield a pooled connection; raise PoolTimeoutError if none comes free.

        `timeout` overrides the pool's acquire timeout for this call.
        """
        wait = self._acquire_timeout if timeout is None else timeout
        self._waiters += 1
        try:
            conn = await self._pool.acquire(timeout=wait)
        except TimeoutError as exc:
            msg = f"no database connection free within {wait:g}s"
            raise PoolTimeoutError(msg) from exc
        finally:
            self._waiters -= 1
        try:
            yield conn
        finally:
            await self._pool.release(conn)

    def busy(self) -> bool:
        """Whether every connection the pool may open is in use."""
        return (
            self._pool.get_size() >= self._pool.get_max_size()
            and self._pool.get_idle_size() == 0
        )

    def size(self) -> int:
        """Connections the pool has open."""
        return self._pool.get_size()

    def max_size(self) -> int:
        """Connections the pool may open."""
        return self._pool.get_max_size()

    def in_use(self) -> int:
        """Open connections lent out to callers."""
        return self._pool.get_size() - self._pool.get_idle_size()

    def waiters(self) -> int:
        """Callers waiting in `acquire()` for a connection."""
        return self._waiters

    async def close(self) -> None:
        """Close every connection, waiting for the ones in use."""
        await self._pool.close()


async def create_pool(
    dsn: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
    acquire_timeout: float = 10,
    command_timeout: float = 30,
) -> Pool:
    """Open a connection pool against the given DSN.

    `command_timeout` bounds every statement, client side: a hung
    connection raises TimeoutError instead of holding its caller.

    Schema migrations are applied out-of-band by `golang-migrate/migrate`
    against `./migrations/`. This factory does not run DDL.
    """
    pool = await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        command_timeout=command_timeout,
    )
    return Pool(pool, acquire_timeout)
