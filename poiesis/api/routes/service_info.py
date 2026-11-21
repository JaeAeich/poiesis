"""TES service-info route.

The TES spec requires `GET /service-info`. The shape is the GA4GH
service-info envelope plus two TES-specific extensions: `storage`
(URI schemes the server can stage from/to) and
`tesResources_backend_parameters` (keys the server honours: those the
operator allows in ``taskpods.backendParameters.allowed``).

The deployment's own fields come from `ServiceInfoSettings`
(``POIESIS_SERVICE_INFO_*``); the values below are used where those
are unset. ``version`` is the version of Poiesis, ``type.version``
the TES version.
"""

from __future__ import annotations

from http import HTTPStatus
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from pydantic import AnyUrl

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.tes.models import (
    Artifact,
    Organization,
    TesServiceInfo,
    TesServiceType,
)
from poiesis.core.services.filer.filer_strategy_factory import (
    supported_input_schemes,
    supported_output_schemes,
)

if TYPE_CHECKING:
    from poiesis.api.settings import ServiceInfoSettings, Settings

router = APIRouter(tags=["TaskService"])

_api_constants = get_poiesis_api_constants()


def _poiesis_version() -> str:
    """Return the installed version of Poiesis."""
    try:
        return version("poiesis")
    except PackageNotFoundError:  # pragma: no cover - always installed
        return "unknown"


_POIESIS_VERSION = _poiesis_version()


@router.get(
    "/service-info",
    status_code=HTTPStatus.OK,
    operation_id="GetServiceInfo",
    response_model_exclude_none=True,
)
async def service_info(request: Request) -> TesServiceInfo:
    """Return TES-compliant service information."""
    config: ServiceInfoSettings = request.app.state.settings.service_info
    # Unset, `createdAt` keeps the model's default (the time of the request).
    created: dict[str, Any] = (
        {} if config.created_at is None else {"createdAt": config.created_at}
    )
    return TesServiceInfo(
        id=config.id,
        name=config.name or "Poiesis",
        description=(
            config.description or "GA4GH TES (Task Execution Service) on Kubernetes"
        ),
        organization=Organization(
            name=config.organization_name or "Poiesis",
            url=AnyUrl(config.organization_url or "https://poiesis.jaeaeich.com"),
        ),
        contactUrl=config.contact_url or "mailto:jh4official@gmail.com",
        documentationUrl=AnyUrl(
            config.documentation_url or "https://poiesis.jaeaeich.com"
        ),
        environment=config.environment,
        type=TesServiceType(
            group="org.ga4gh",
            artifact=Artifact.tes,
            version=_api_constants.TES_VERSION,
        ),
        version=_POIESIS_VERSION,
        storage=_supported_storage_schemes(request.app.state.settings),
        tesResources_backend_parameters=sorted(
            request.app.state.settings.scheduling.config().backend_parameters
        ),
        **created,
    )


def _supported_storage_schemes(settings: Settings) -> list[str]:
    """Return the URL-scheme prefixes the filer strategies can stage from/to.

    An object-store scheme is listed only when its provider is enabled.
    """
    schemes = set(supported_input_schemes()) | set(supported_output_schemes())
    return sorted(
        f"{name}://"
        for name in schemes
        if name != "content" and settings.storage_enabled(name)
    )
