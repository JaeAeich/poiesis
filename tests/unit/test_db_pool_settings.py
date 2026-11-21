"""Pool size and database timeouts are settings, parsed strictly (#164)."""

from __future__ import annotations

import asyncio
from typing import Any

import click
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from poiesis.api.exceptions import handle_pool_timeout
from poiesis.api.settings import DatabaseSettings
from poiesis.cli.commands.poiesis import tctl as tctl_cli
from poiesis.db import pool as pool_module
from poiesis.db.pool import Pool, PoolTimeoutError

ENV = (
    "POIESIS_DATABASE_POOL_MIN_SIZE",
    "POIESIS_DATABASE_POOL_MAX_SIZE",
    "POIESIS_DATABASE_POOL_ACQUIRE_TIMEOUT_SECONDS",
    "POIESIS_DATABASE_COMMAND_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def test_defaults_keep_todays_pool() -> None:
    settings = DatabaseSettings()
    assert (settings.pool_min_size, settings.pool_max_size) == (1, 10)
    assert settings.acquire_timeout_seconds == 10  # noqa: PLR2004
    assert settings.command_timeout_seconds == 30  # noqa: PLR2004


def test_env_sets_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POIESIS_DATABASE_POOL_MIN_SIZE", "0")
    monkeypatch.setenv("POIESIS_DATABASE_POOL_MAX_SIZE", "25")
    monkeypatch.setenv("POIESIS_DATABASE_POOL_ACQUIRE_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("POIESIS_DATABASE_COMMAND_TIMEOUT_SECONDS", "60")
    settings = DatabaseSettings()
    assert (settings.pool_min_size, settings.pool_max_size) == (0, 25)
    assert settings.acquire_timeout_seconds == 2.5  # noqa: PLR2004
    assert settings.command_timeout_seconds == 60  # noqa: PLR2004


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("POIESIS_DATABASE_POOL_MAX_SIZE", "ten"),
        ("POIESIS_DATABASE_POOL_MAX_SIZE", "0"),
        ("POIESIS_DATABASE_POOL_MIN_SIZE", "11"),
        ("POIESIS_DATABASE_POOL_MIN_SIZE", "-1"),
        ("POIESIS_DATABASE_POOL_ACQUIRE_TIMEOUT_SECONDS", "0"),
        ("POIESIS_DATABASE_POOL_ACQUIRE_TIMEOUT_SECONDS", "inf"),
        ("POIESIS_DATABASE_COMMAND_TIMEOUT_SECONDS", "-5"),
        ("POIESIS_DATABASE_COMMAND_TIMEOUT_SECONDS", "30s"),
    ],
)
def test_bad_values_stop_startup(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="POIESIS_DATABASE_"):
        DatabaseSettings()


def test_create_pool_passes_sizes_and_command_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def create_pool(dsn: str, **kwargs: Any) -> object:
        seen.update(kwargs, dsn=dsn)
        return object()

    monkeypatch.setattr(pool_module.asyncpg, "create_pool", create_pool)
    pool = asyncio.run(
        pool_module.create_pool(
            "dsn", min_size=2, max_size=7, acquire_timeout=3, command_timeout=9
        )
    )
    assert isinstance(pool, Pool)
    assert seen == {"dsn": "dsn", "min_size": 2, "max_size": 7, "command_timeout": 9}


class ExhaustedPool:
    """An asyncpg pool with every connection in use."""

    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    async def acquire(self, *, timeout: float | None) -> None:
        self.timeouts.append(timeout)
        raise TimeoutError

    def get_size(self) -> int:
        return 10

    def get_max_size(self) -> int:
        return 10

    def get_idle_size(self) -> int:
        return 0


def test_acquire_waits_the_acquire_timeout_then_raises() -> None:
    inner = ExhaustedPool()
    pool = Pool(inner, acquire_timeout=4)  # ty: ignore[invalid-argument-type]

    async def acquire() -> None:
        async with pool.acquire():
            pass  # pragma: no cover

    with pytest.raises(PoolTimeoutError, match="within 4s"):
        asyncio.run(acquire())
    assert inner.timeouts == [4]
    assert pool.busy()


def test_tctl_refuses_a_bad_command_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(tctl_cli._COMMAND_TIMEOUT_ENV, "soon")
    with pytest.raises(click.ClickException):
        tctl_cli._timeout_env(tctl_cli._COMMAND_TIMEOUT_ENV)


def test_a_busy_pool_is_a_503_with_retry_after() -> None:
    """The app maps PoolTimeoutError to 503, not the generic 500."""
    app = FastAPI()
    app.add_exception_handler(PoolTimeoutError, handle_pool_timeout)

    @app.get("/x")
    async def busy() -> None:
        raise PoolTimeoutError("no database connection free within 10s")

    response = TestClient(app).get("/x")
    assert response.status_code == 503  # noqa: PLR2004
    assert response.headers["Retry-After"] == "1"
    assert response.json()["error"] == "service_unavailable"
