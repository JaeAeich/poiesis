"""Handles security for the API.

Entrypoint of token validations.
"""

from typing import Any

from poiesis.api.auth.auth_factory import get_auth_provider
from poiesis.api.exceptions import UnauthorizedException


def validate_bearer_token(token: str) -> dict[str, Any]:
    """Validate bearer token.

    This function validates a bearer token and returns the token info. This info is then
    added to the context for use in the API handlers.

    Args:
        token: The bearer token.

    Returns:
        dict[str, Any]: The token info.
    """
    auth_provider = get_auth_provider()
    try:
        token_info = auth_provider.validate_token(token)
    except Exception as e:
        raise UnauthorizedException("Invalid or expired token") from e
    return token_info
