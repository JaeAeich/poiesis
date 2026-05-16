"""FastAPI dependency-injection helpers.

Yield per-request resources from the app-state objects built in the
`lifespan` (see `app.py`).

Note: this module does NOT use `from __future__ import annotations`.
FastAPI introspects route handler signatures at runtime to wire DI, so
the type imports must be live, not deferred.
"""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request

from poiesis.core.taskpod import RuntimeConfig
from poiesis.k8s import K8sClient


async def get_db_conn(request: Request) -> AsyncIterator[Any]:
    """Yield a pooled asyncpg connection for the duration of the request.

    The yield type is `Any` because asyncpg's `pool.acquire()` returns a
    `PoolConnectionProxy` that duck-types as `Connection` but doesn't
    formally inherit from it; downstream `poiesis.db.tasks` / `state`
    functions accept either via the asyncpg query protocol.
    """
    async with request.app.state.db_pool.acquire() as conn:
        yield conn


def get_k8s(request: Request) -> K8sClient:
    """Return the process-wide K8s client wrapper."""
    return request.app.state.k8s


def get_runtime_config(request: Request) -> RuntimeConfig:
    """Return the TaskPod RuntimeConfig derived from Settings."""
    return request.app.state.runtime_config
