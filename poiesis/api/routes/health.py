"""Kubernetes probe endpoints.

- `/healthz`: liveness — the process is up. No dependency checks; a failure
    here means restart the pod.
- `/readyz`: readiness — the API can reach its database. Pings it; a
    failure removes the pod from the Service endpoints. A pool with every
    connection in use counts as ready: see `readyz`.
- `/startupz`: startup — initialisation finished (db pool built). Gives
    slow boots time before liveness/readiness kick in.
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Request, Response, status

router = APIRouter(tags=["health"])

#: Seconds `/readyz` waits for a free connection, then for `SELECT 1`;
#: together well inside the chart's 2-second probe timeout.
_ACQUIRE_TIMEOUT_SECONDS = 0.5
_PING_TIMEOUT_SECONDS = 1


@router.get("/healthz", include_in_schema=False)
async def healthz() -> Response:
    """Liveness — always 200 if the event loop is responsive."""
    return Response(status_code=status.HTTP_200_OK)


@router.get("/readyz", include_in_schema=False)
async def readyz(request: Request) -> Response:
    """Readiness — the API can talk to its database.

    A pool with every connection in use is ready: those connections are
    serving requests, so Postgres answers, and the replica's requests
    wait for one (or get a 503 after the acquire timeout). Reporting it
    unready would, under a load that fills every replica's pool, take all
    of them out of the Service at once. A pool stuck on a Postgres that
    stopped answering frees its connections once their statements time
    out (`database.commandTimeoutSeconds`); the next probe then fails.
    """
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if pool.busy():
        return Response(status_code=status.HTTP_200_OK)
    try:
        async with pool.acquire(timeout=_ACQUIRE_TIMEOUT_SECONDS) as conn:
            await conn.execute("SELECT 1", timeout=_PING_TIMEOUT_SECONDS)
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError):
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(status_code=status.HTTP_200_OK)


@router.get("/startupz", include_in_schema=False)
async def startupz(request: Request) -> Response:
    """Startup — lifespan finished building the db pool."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(status_code=status.HTTP_200_OK)
