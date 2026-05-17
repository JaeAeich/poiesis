"""TES service-info route.

The TES spec requires `GET /service-info`. The shape is the GA4GH
service-info envelope plus two TES-specific extensions: `storage`
(URI schemes the server can stage from/to) and
`tesResources_backend_parameters` (keys the server honours).
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter
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

router = APIRouter(tags=["TaskService"])

_api_constants = get_poiesis_api_constants()


@router.get(
    "/service-info",
    status_code=HTTPStatus.OK,
    operation_id="GetServiceInfo",
    response_model_exclude_none=True,
)
async def service_info() -> TesServiceInfo:
    """Return TES-compliant service information."""
    return TesServiceInfo(
        id="org.ga4gh.poiesis",
        name="Poiesis",
        description="GA4GH TES (Task Execution Service) on Kubernetes",
        organization=Organization(
            name="Poiesis",
            url=AnyUrl("https://poiesis.jaeaeich.com"),
        ),
        contactUrl="mailto:jh4official@gmail.com",
        documentationUrl=AnyUrl("https://poiesis.jaeaeich.com"),
        type=TesServiceType(
            group="org.ga4gh",
            artifact=Artifact.tes,
            version=_api_constants.TES_VERSION,
        ),
        version=_api_constants.TES_VERSION,
        storage=_supported_storage_schemes(),
        tesResources_backend_parameters=[],
    )


def _supported_storage_schemes() -> list[str]:
    """Return the URL-scheme prefixes the filer strategies can stage from/to."""
    schemes = set(supported_input_schemes()) | set(supported_output_schemes())
    return sorted(f"{name}://" for name in schemes if name != "content")
