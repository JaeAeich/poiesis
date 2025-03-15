"""Exceptions and their handlers for the platform backend."""

import json
import logging
from http import HTTPStatus
from typing import Any

from connexion.lifecycle import ConnexionRequest, ConnexionResponse

logger = logging.getLogger(__name__)


class APIException(Exception):
    """Base exception for all API errors."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR.value
    error_code = "internal_error"

    def __init__(self, message=None, details=None):
        """Initialize the exception with an optional message and details."""
        self.message = message or self.__doc__
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to a dict representation."""
        result = {"error": self.error_code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result


def handle_api_exception(
    request: ConnexionRequest, exc: APIException
) -> ConnexionResponse:
    """Handler for our custom APIException hierarchy."""
    if exc.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR.value:
        logger.error(f"Server error: {exc.message}", exc_info=True)
    else:
        logger.warning(f"Client error: {exc.message}")

    return ConnexionResponse(
        status_code=exc.status_code,
        body=json.dumps(exc.to_dict()),
        mimetype="application/json",
    )


def handle_unexpected_exception(
    request: ConnexionRequest, exc: Exception
) -> ConnexionResponse:
    """Handler for unexpected exceptions."""
    logger.error(f"Unexpected error processing request: {request.path}", exc_info=True)

    error_response = {
        "error": "internal_error",
        "message": "An unexpected error occurred",
    }

    return ConnexionResponse(
        status_code=500, body=json.dumps(error_response), mimetype="application/json"
    )

