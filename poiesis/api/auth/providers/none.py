"""None authentication provider."""

from typing import Any

from poiesis.api.auth.providers.auth import AuthProvider


class NoneAuthProvider(AuthProvider):
    """None authentication provider."""

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validate a token and return user information."""
        return {"valid": True, "user": "-1"}
