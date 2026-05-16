"""Poiesis API constants."""

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class PoiesisApiConstants:
    """Constants used in the Poiesis API.

    Attributes:
        SPEC_GIT_HASH: Git hash of the GA4GH TES OpenAPI specification that
            the API is derived from. The shipped spec file is named
            `<SPEC_GIT_HASH>.openapi.yaml` and may differ from upstream by
            implementor-specific but compliant edits.
        TES_VERSION: TES API version implemented.
        BASE_PATH: URL prefix the FastAPI router is mounted under.
    """

    SPEC_GIT_HASH = "c4c17c9"
    TES_VERSION = "v1.1.0"
    BASE_PATH = "ga4gh/tes/v1"


@lru_cache
def get_poiesis_api_constants() -> PoiesisApiConstants:
    """Get the Poiesis API constants."""
    return PoiesisApiConstants()
