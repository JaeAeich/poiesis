"""Dummy authentication provider."""

from typing import Any

from poiesis.api.auth.providers.auth import AuthProvider


class DummyAuthProvider(AuthProvider):
    """Dummy authentication provider.

    Validate any token and return a `-1` user id.
    """

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validate any token and return user information."""
        return {"valid": True, "sub": "-1"}
