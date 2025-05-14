"""Main module of the Poiesis API.

This module creates and configures the connexion app.
"""

import logging
from pathlib import Path

from connexion import AsyncApp
from connexion.resolver import RelativeResolver

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import (
    APIException,
    handle_api_exception,
    handle_unexpected_exception,
)
from poiesis.constants import get_poiesis_constants

constants = get_poiesis_constants()
api_constant = get_poiesis_api_constants()


def create_app() -> AsyncApp:
    """Create the connexion app.

    Returns:
        AsyncApp: The connexion app.
    """
    openapi_spec_directory = Path(__file__).parent / "tes" / "spec"

    logging.basicConfig(level=getattr(logging, constants.LOG_LEVEL))

    app = AsyncApp(
        __name__,
        specification_dir=openapi_spec_directory,
    )

    app.add_api(
        f"{api_constant.SPEC_GIT_HASH}.openapi.yaml",
        resolver=RelativeResolver("poiesis.api.api_handlers"),
        validate_responses=True,
    )
    app.add_error_handler(Exception, handle_unexpected_exception)
    app.add_error_handler(APIException, handle_api_exception)

    return app


app = create_app()
