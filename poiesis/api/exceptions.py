"""Exceptions and their handlers for the API layer."""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Base exception for all API errors."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR.value
    error_code = "internal_error"

    def __init__(self, message: str | None = None, details: Any | None = None) -> None:
        """Initialize the exception with an optional message and details."""
        self.message = message or self.__doc__
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to a dict representation."""
        result: dict[str, Any] = {"error": self.error_code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result


async def handle_api_exception(request: Request, exc: Exception) -> JSONResponse:
    """Handler for our custom APIError hierarchy.

    The signature takes the broader `Exception` type to satisfy Starlette's
    handler protocol; the registration call binds this only to `APIError`,
    so the cast is safe at runtime.
    """
    err = exc if isinstance(exc, APIError) else APIError(str(exc))
    if err.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR.value:
        logger.error("Server error: %s", err.message)
    else:
        logger.warning("Client error: %s", err.message)

    return JSONResponse(status_code=err.status_code, content=err.to_dict())


async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
    """Handler for unexpected exceptions."""
    logger.exception("Unexpected error processing %s", request.url.path)
    _ = exc  # signature required by Starlette; not used directly

    return JSONResponse(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred",
        },
    )


class BadRequestError(APIError):
    """The request was invalid or cannot be served."""

    status_code = HTTPStatus.BAD_REQUEST.value
    error_code = "bad_request"


class UnauthorizedError(APIError):
    """The request is unauthorized."""

    status_code = HTTPStatus.UNAUTHORIZED.value
    error_code = "unauthorized"


class NotFoundError(APIError):
    """The requested resource was not found."""

    status_code = HTTPStatus.NOT_FOUND.value
    error_code = "not_found"


class InternalServerError(APIError):
    """An unexpected condition was encountered."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR.value
    error_code = "internal_error"


class DBError(APIError):
    """An error occurred with the database."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR.value
    error_code = "db_error"
