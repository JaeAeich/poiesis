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

    headers: dict[str, str] = {}
    retry_after = getattr(err, "retry_after_seconds", None)
    if isinstance(retry_after, int) and retry_after > 0:
        headers["Retry-After"] = str(retry_after)

    return JSONResponse(
        status_code=err.status_code, content=err.to_dict(), headers=headers or None
    )


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


class NotFoundError(APIError):
    """The requested resource was not found."""

    status_code = HTTPStatus.NOT_FOUND.value
    error_code = "not_found"


class InternalServerError(APIError):
    """An unexpected condition was encountered."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR.value
    error_code = "internal_error"


class ServiceUnavailableError(APIError):
    """The server is temporarily unable to handle the request.

    Used for back-pressure on operator-side capacity limits (Kubernetes
    quota exceeded, etc.). The client is expected to retry after the
    advertised interval.
    """

    status_code = HTTPStatus.SERVICE_UNAVAILABLE.value
    error_code = "service_unavailable"

    def __init__(
        self,
        message: str | None = None,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        """Capture an optional ``Retry-After`` hint alongside the message."""
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
