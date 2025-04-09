"""Base class for authentication providers."""

from abc import abstractmethod
from typing import Any


class AuthProvider:
    """Abstract base class for authentication providers."""

    @abstractmethod
    def validate_token(self, token: str) -> dict[str, Any]:
        """Validate a token and return user information."""
        pass
