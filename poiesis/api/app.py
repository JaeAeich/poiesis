"""Poiesis API entrypoint.

Owns FastAPI app construction, the startup lifespan that builds the
asyncpg pool + Kubernetes client, and global exception-handler wiring.
Per-aggregate routers (Tasks, ServiceInfo, ...) are mounted from
`poiesis.api.routes.*` modules.

Settings are read when the app is built (:func:`create_app`), since
they decide which routers are mounted and what the OpenAPI document
offers; the lifespan reuses them.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Security
from fastapi.security import HTTPBearer, OpenIdConnect

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from poiesis.api.auth import Authenticator
    from poiesis.api.settings import AuthSettings, Settings

from poiesis.api import audit
from poiesis.api.apikey_auth import ApiKeyAuthenticator
from poiesis.api.authz import Authz
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import (
    APIError,
    handle_api_exception,
    handle_unexpected_exception,
)
from poiesis.api.jwt_auth import JWTAuthenticator
from poiesis.api.routes import api_keys as api_keys_routes
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
    settings: Settings = app.state.settings
    app.state.authz = Authz(settings.authz, settings.auth.issuers)
    app.state.runtime_config = settings.runtime_config()

    logger.info("Connecting to Postgres at %s", _redact_dsn(settings.database_url))
    app.state.db_pool = await create_pool(settings.database_url)

    load_config()
    app.state.k8s = K8sClient()
    logger.info("Kubernetes client ready (namespace=%s)", settings.poiesis_namespace)

    if settings.auth.enabled:
        authenticators: list[Authenticator] = [JWTAuthenticator(settings.auth.issuers)]
        if settings.auth.api_keys.enabled:
            # After the JWT link: it only claims `poi_` credentials, which
            # never look like a JWT, so the order costs JWTs nothing.
            authenticators.append(
                ApiKeyAuthenticator(app.state.db_pool, settings.auth.issuers)
            )
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


def _docs_security(auth: AuthSettings) -> list[Any]:
    """Return the security schemes the OpenAPI document shows, as dependencies.

    They give the Swagger UI at ``/docs`` its *Authorize* button: a
    bearer field (for a token or an API key) whenever auth is on, and an
    OpenID Connect login (authorization code + PKCE) when
    ``auth.swaggerUi`` is set. Documentation only: with
    ``auto_error=False`` they never reject a request; authentication is
    the authenticator chain's.
    """
    if not auth.enabled:
        return []
    schemes = [
        Security(
            HTTPBearer(
                scheme_name="bearer",
                description="An access token of a configured issuer, or a "
                "Poiesis API key (`poi_…`).",
                auto_error=False,
            )
        )
    ]
    login = auth.swagger_ui
    if login is not None:
        discovery = login.issuer.rstrip("/") + "/.well-known/openid-configuration"
        schemes.append(
            Security(
                OpenIdConnect(
                    openIdConnectUrl=discovery,
                    scheme_name="oidc",
                    description=f"Log in at {login.issuer}.",
                    auto_error=False,
                ),
                scopes=login.scopes.split(),
            )
        )
    return schemes


def _swagger_ui_oauth(auth: AuthSettings) -> dict[str, Any] | None:
    """Return the Swagger UI's OAuth client settings, if a login is set."""
    login = auth.swagger_ui
    if not auth.enabled or login is None:
        return None
    return {
        "clientId": login.client_id,
        "usePkceWithAuthorizationCodeGrant": True,
        "scopes": login.scopes,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the FastAPI app for ``settings`` (default: from env).

    Invalid settings raise here, before anything connects anywhere.
    """
    logging.basicConfig(level=getattr(logging, constants.LOG_LEVEL))
    settings = settings or load_settings()
    settings.authz.validate_for(auth_enabled=settings.auth.enabled)
    audit.configure(enabled=settings.audit.enabled)

    app = FastAPI(
        title="Poiesis",
        description="GA4GH TES (Task Execution Service) on Kubernetes",
        version=api_constants.TES_VERSION,
        lifespan=lifespan,
        swagger_ui_init_oauth=_swagger_ui_oauth(settings.auth),
    )
    app.state.settings = settings

    app.add_exception_handler(APIError, handle_api_exception)
    app.add_exception_handler(Exception, handle_unexpected_exception)
    # The request id of audit lines, echoed in every response.
    app.add_middleware(audit.RequestIdMiddleware)

    security = _docs_security(settings.auth)
    # Mount under the TES-canonical prefix so direct callers and the
    # GA4GH compliance suite both hit `<host>/ga4gh/tes/v1/tasks`.
    prefix = f"/{api_constants.BASE_PATH}"
    app.include_router(tasks_routes.router, prefix=prefix, dependencies=security)
    app.include_router(service_info_routes.router, prefix=prefix)
    if settings.auth.enabled and settings.auth.api_keys.enabled:
        # Poiesis's own API, outside the TES namespace.
        app.include_router(
            api_keys_routes.router, prefix="/poiesis/v1", dependencies=security
        )
    # Probes are unprefixed so kubelet hits /healthz, /readyz, /startupz directly.
    app.include_router(health_routes.router)

    return app
