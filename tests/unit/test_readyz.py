"""`/readyz` under load: a busy pool is ready, a broken database is not (#164).

`/readyz` waited for a pooled connection like any request. When a burst
filled every replica's pool, every replica failed its probe and left the
Service at once.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from poiesis.api.routes import health
from poiesis.db.pool import Pool, PoolTimeoutError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class FakeAsyncpgPool:
    """The asyncpg pool under `Pool`: `size` connections, `in_use` taken."""

    def __init__(self, *, size: int, in_use: int, max_size: int = 10) -> None:
        self.size, self.in_use, self.max_size = size, in_use, max_size
        self.acquire_timeouts: list[float | None] = []
        self.ping_timeouts: list[float | None] = []
        self.ping_error: Exception | None = None

    def get_size(self) -> int:
        return self.size

    def get_idle_size(self) -> int:
        return self.size - self.in_use

    def get_max_size(self) -> int:
        return self.max_size

    async def acquire(self, *, timeout: float | None) -> FakeAsyncpgPool:
        self.acquire_timeouts.append(timeout)
        if self.in_use >= self.max_size:
            raise TimeoutError
        return self

    async def release(self, _conn: Any) -> None:
        pass

    async def execute(self, query: str, *, timeout: float | None) -> None:
        assert query == "SELECT 1"
        self.ping_timeouts.append(timeout)
        if self.ping_error is not None:
            raise self.ping_error


def probe(pool: Any) -> int:
    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=pool))
    )
    return asyncio.run(health.readyz(request)).status_code


def wrap(inner: FakeAsyncpgPool) -> Pool:
    return Pool(inner, acquire_timeout=10)  # ty: ignore[invalid-argument-type]


def test_a_full_pool_is_still_ready() -> None:
    inner = FakeAsyncpgPool(size=10, in_use=10)
    assert probe(wrap(inner)) == 200  # noqa: PLR2004
    assert inner.acquire_timeouts == []


def test_a_reachable_database_is_ready_with_short_timeouts() -> None:
    inner = FakeAsyncpgPool(size=2, in_use=1)
    assert probe(wrap(inner)) == 200  # noqa: PLR2004
    assert inner.acquire_timeouts == [health._ACQUIRE_TIMEOUT_SECONDS]
    assert inner.ping_timeouts == [health._PING_TIMEOUT_SECONDS]
    budget = health._ACQUIRE_TIMEOUT_SECONDS + health._PING_TIMEOUT_SECONDS
    assert budget < 2  # noqa: PLR2004


@pytest.mark.parametrize(
    "error",
    [OSError("connection refused"), TimeoutError()],
    ids=["down", "hung"],
)
def test_a_database_that_does_not_answer_is_not_ready(error: Exception) -> None:
    inner = FakeAsyncpgPool(size=2, in_use=0)
    inner.ping_error = error
    assert probe(wrap(inner)) == 503  # noqa: PLR2004


def test_no_connection_within_the_probe_budget_is_not_ready() -> None:
    """The pool has room but can't open a connection in time: Postgres is slow."""

    class Stuck:
        def busy(self) -> bool:
            return False

        @contextlib.asynccontextmanager
        async def acquire(self, *, timeout: float) -> AsyncIterator[None]:
            assert timeout == health._ACQUIRE_TIMEOUT_SECONDS
            raise PoolTimeoutError
            yield  # pragma: no cover

    assert probe(Stuck()) == 503  # noqa: PLR2004


def test_no_pool_yet_is_not_ready() -> None:
    assert probe(None) == 503  # noqa: PLR2004
