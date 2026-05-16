"""Kubernetes probe endpoints.

- `/healthz`: liveness — the process is up. No dependency checks; a failure
  here means restart the pod.
- `/readyz`: readiness — the API can serve a request right now. Pings the
  database; a failure removes the pod from the Service endpoints.
- `/startupz`: startup — initialisation finished (db pool built). Gives
  slow boots time before liveness/readiness kick in.
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Request, Response, status

router = APIRouter(tags=["health"])


@router.get("/healthz", include_in_schema=False)
async def healthz() -> Response:
    """Liveness — always 200 if the event loop is responsive."""
    return Response(status_code=status.HTTP_200_OK)


@router.get("/readyz", include_in_schema=False)
async def readyz(request: Request) -> Response:
    """Readiness — the API can talk to its database."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
    except (asyncpg.PostgresError, OSError, TimeoutError):
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(status_code=status.HTTP_200_OK)


@router.get("/startupz", include_in_schema=False)
async def startupz(request: Request) -> Response:
    """Startup — lifespan finished building the db pool."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(status_code=status.HTTP_200_OK)
