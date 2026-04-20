"""Poiesis API entrypoint.

Builds the FastAPI application. Routes for `CreateTask`, `GetTask`,
`ListTasks`, and `CancelTask` are added in later slices of the v0.2.0
redesign; this module owns app construction and global wiring only.
"""

import logging

from fastapi import FastAPI

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import (
    APIError,
    handle_api_exception,
    handle_unexpected_exception,
)
from poiesis.constants import get_poiesis_constants

constants = get_poiesis_constants()
api_constants = get_poiesis_api_constants()


def create_app() -> FastAPI:
    """Build and return the FastAPI app."""
    logging.basicConfig(level=getattr(logging, constants.LOG_LEVEL))

    app = FastAPI(
        title="Poiesis",
        description="GA4GH TES (Task Execution Service) on Kubernetes",
        version=api_constants.TES_VERSION,
        root_path=f"/{api_constants.BASE_PATH}",
    )

    app.add_exception_handler(APIError, handle_api_exception)
    app.add_exception_handler(Exception, handle_unexpected_exception)

    return app


app = create_app()
