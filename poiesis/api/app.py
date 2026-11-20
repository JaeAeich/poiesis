"""Poiesis API entrypoint.

Owns FastAPI app construction, the startup lifespan that builds the
asyncpg pool + Kubernetes client, and global exception-handler wiring.
Per-aggregate routers (Tasks, ServiceInfo, ...) are mounted from
`poiesis.api.routes.*` modules.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from poiesis.api.auth import Authenticator

from poiesis.api.authz import Authz
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import (
    APIError,
    handle_api_exception,
    handle_unexpected_exception,
)
from poiesis.api.jwt_auth import JWTAuthenticator
from poiesis.api.routes import health as health_routes
from poiesis.api.routes import service_info as service_info_routes
from poiesis.api.routes import tasks as tasks_routes
from poiesis.api.settings import load_settings
from poiesis.constants import get_poiesis_constants
from poiesis.db import create_pool
from poiesis.k8s import K8sClient, load_config

logger = logging.getLogger(__name__)

constants = get_poiesis_constants()
api_constants = get_poiesis_api_constants()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build process-wide resources at startup, tear them down at shutdown."""
    settings = load_settings()
    settings.authz.validate_for(auth_enabled=settings.auth.enabled)
    app.state.authz = Authz(settings.authz)
    app.state.settings = settings
    app.state.runtime_config = settings.runtime_config()

    logger.info("Connecting to Postgres at %s", _redact_dsn(settings.database_url))
    app.state.db_pool = await create_pool(settings.database_url)

    load_config()
    app.state.k8s = K8sClient()
    logger.info("Kubernetes client ready (namespace=%s)", settings.poiesis_namespace)

    if settings.auth.enabled:
        authenticators: list[Authenticator] = [JWTAuthenticator(settings.auth.issuers)]
        try:
            for authenticator in authenticators:
                await authenticator.start()
        except BaseException:
            await _close(authenticators)
            raise
        app.state.authenticators = authenticators
    else:
        app.state.authenticators = None
        logger.warning("Auth is DISABLED; all requests will run as anonymous")

    try:
        yield
    finally:
        await app.state.authz.aclose()
        if app.state.authenticators is not None:
            await _close(app.state.authenticators)
        logger.info("Closing Postgres pool")
        await app.state.db_pool.close()


async def _close(authenticators: list[Authenticator]) -> None:
    """Close every authenticator, in order."""
    for authenticator in authenticators:
        await authenticator.aclose()


def _redact_dsn(dsn: str) -> str:
    """Mask the password in a DSN for log output."""
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    creds, host = rest.split("@", 1)
    if ":" in creds:
        user, _ = creds.split(":", 1)
        return f"{scheme}://{user}:***@{host}"
    return dsn


def create_app() -> FastAPI:
    """Build and return the FastAPI app."""
    logging.basicConfig(level=getattr(logging, constants.LOG_LEVEL))

    app = FastAPI(
        title="Poiesis",
        description="GA4GH TES (Task Execution Service) on Kubernetes",
        version=api_constants.TES_VERSION,
        lifespan=lifespan,
    )

    app.add_exception_handler(APIError, handle_api_exception)
    app.add_exception_handler(Exception, handle_unexpected_exception)

    # Mount under the TES-canonical prefix so direct callers and the
    # GA4GH compliance suite both hit `<host>/ga4gh/tes/v1/tasks`.
    prefix = f"/{api_constants.BASE_PATH}"
    app.include_router(tasks_routes.router, prefix=prefix)
    app.include_router(service_info_routes.router, prefix=prefix)
    # Probes are unprefixed so kubelet hits /healthz, /readyz, /startupz directly.
    app.include_router(health_routes.router)

    return app


app = create_app()
