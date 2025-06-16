"""Provides a generic OAuth2 authentication provider."""

import logging
import os
from typing import Any

import requests
from requests import RequestException

from poiesis.api.auth.providers.auth import AuthProvider
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import InternalServerException

logger = logging.getLogger(__name__)

constants = get_poiesis_api_constants()


class OAuth2AuthProvider(AuthProvider):
    """A generic OAuth2 authentication provider.

    This class validates bearer tokens by checking them against the OAuth2
    provider's userinfo endpoint or, as a fallback, the introspection endpoint.

    Attributes:
        client_id: The OAuth2 client ID.
        client_secret: The OAuth2 client secret.
        issuer: The URL of the token issuer.
        token_endpoint: The URL of the token endpoint.
        userinfo_endpoint: The URL of the userinfo endpoint.
        introspect_endpoint: The optional URL of the introspection endpoint.
    """

    def __init__(self):
        """Initializes the OAuth2AuthProvider with configuration."""
        self.client_id = constants.Auth.OAuth2.CLIENT_ID
        self.client_secret = os.getenv("OAUTH2_CLIENT_SECRET")
        self.issuer = constants.Auth.OAuth2.ISSUER

        missing = []
        if not self.client_id:
            missing.append("OAUTH2_CLIENT_ID")
        if not self.issuer:
            missing.append("OAUTH2_ISSUER")

        if missing:
            logger.error(f"Missing required OAuth2 configuration: {', '.join(missing)}")
            raise InternalServerException("Internal authorization server error.")
        # After the missing check, we know self.issuer is not None
        self.issuer = self.issuer.rstrip("/")  # type: ignore
        self.userinfo_endpoint = constants.Auth.OAuth2.USERINFO_ENDPOINT
        self.introspect_endpoint = constants.Auth.OAuth2.INTROSPECT_ENDPOINT

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validates a bearer token.

        It first attempts validation using the userinfo endpoint. If that fails
        or is not available, it tries the introspection endpoint as a fallback.

        Args:
            token: The bearer token to validate.

        Returns:
            A dictionary containing the token's claims if valid.

        Raises:
            ValueError: If the token is invalid or validation fails for any reason.
        """
        try:
            return self._validate_with_userinfo(token)
        except ValueError as userinfo_error:
            logger.warning(
                f"Userinfo validation failed: {userinfo_error}.Trying introspection."
            )
            if not self.introspect_endpoint:
                raise InternalServerException(
                    "Token validation failed, and no introspection endpoint is "
                    "configured."
                ) from userinfo_error
            try:
                return self._validate_with_introspection(token)
            except ValueError as introspect_error:
                raise ValueError(
                    "Token introspection also failed."
                ) from introspect_error

    def _validate_with_userinfo(self, token: str) -> dict[str, Any]:
        """Validates a token using the userinfo endpoint."""
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = requests.get(self.userinfo_endpoint, headers=headers, timeout=5)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            raise ValueError(f"Userinfo request failed: {e}") from e

    def _validate_with_introspection(self, token: str) -> dict[str, Any]:
        """Validates a token using the introspection endpoint."""
        data = {
            "token": token,
            "client_id": self.client_id,
        }

        if self.client_secret:
            data["client_secret"] = self.client_secret

        try:
            response = requests.post(self.introspect_endpoint, data=data, timeout=5)
            response.raise_for_status()
            token_info = response.json()

            if not token_info.get("active"):
                raise ValueError("Token is inactive.")

            return token_info
        except RequestException as e:
            raise ValueError(f"Token introspection request failed: {e}") from e
