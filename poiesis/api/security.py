"""Handles security for the API.

Entrypoint of token validations.
"""

from typing import Any


def validate_bearer_token(*args, **kwargs) -> dict[str, Any]:
    """Validate bearer token.

    Args:
        args: The arguments.
        kwargs: The keyword arguments.

    Returns:
        The user info and permissions.
    """
    # TODO: Implement real token validation, this should return
    # user info and permissions.
    return {"valid": True}
