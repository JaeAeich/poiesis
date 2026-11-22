"""FastAPI dependency-injection helpers.

Yield per-request resources from the app-state objects built in the
`lifespan` (see `app.py`).

Note: this module does NOT use `from __future__ import annotations`.
FastAPI introspects route handler signatures at runtime to wire DI, so
the type imports must be live, not deferred.
"""

from typing import Any

from fastapi import Request

from poiesis.core.taskpod import RuntimeConfig
from poiesis.k8s import K8sClient


def get_db_pool(request: Request) -> Any:
    """Return the process-wide asyncpg pool.

    For routes that call the decision service: they acquire a
    connection around their database work only, so a slow decision
    never holds a pooled connection (and can't starve other routes).
    """
    return request.app.state.db_pool


def get_k8s(request: Request) -> K8sClient:
    """Return the process-wide K8s client wrapper."""
    return request.app.state.k8s


def get_runtime_config(request: Request) -> RuntimeConfig:
    """Return the TaskPod RuntimeConfig derived from Settings."""
    return request.app.state.runtime_config
