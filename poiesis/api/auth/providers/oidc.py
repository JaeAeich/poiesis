"""Provides a generic OAuth2 authentication provider."""

import logging
import os
from typing import Any

import requests
from requests import RequestException

from poiesis.api.auth.providers.auth import AuthProvider
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import InternalServerException, UnauthorizedException

logger = logging.getLogger(__name__)

constants = get_poiesis_api_constants()


class OpenIDConnectAuthProvider(AuthProvider):
    """A generic OpenID Connect authentication provider.

    This class validates bearer tokens by checking them against the OpenID Connect
    provider's introspection endpoint.

    Attributes:
        client_id: The OpenID Connect client ID.
        client_secret: The OpenID Connect client secret.
        issuer: The URL of the token issuer.
        introspect_endpoint: The URL of the introspection endpoint.
    """

    def __init__(self):
        """Initializes the OpenIDConnectAuthProvider with configuration."""
        logger.debug("Initializing OpenIDConnectAuthProvider")
        self.client_id = constants.Auth.OIDC.CLIENT_ID
        self.client_secret = os.getenv("OIDC_CLIENT_SECRET")
        self.issuer = constants.Auth.OIDC.ISSUER
        self.introspect_endpoint = constants.Auth.OIDC.INTROSPECT_ENDPOINT

        missing = []
        if not self.client_id:
            missing.append("OIDC_CLIENT_ID")
        if not self.issuer:
            missing.append("OIDC_ISSUER")
        if not self.client_secret:
            missing.append("OIDC_CLIENT_SECRET")

        if missing:
            logger.error(
                f"Missing required OpenID Connect configuration: {', '.join(missing)}"
            )
            raise InternalServerException("Internal authorization server error.")

        logger.debug(f"OpenID Connect configuration loaded - Issuer: {self.issuer}")
        self.issuer = self.issuer.rstrip("/")  # type: ignore

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validates a bearer token using the introspection endpoint.

        Args:
            token: The bearer token to validate.

        Returns:
            A dictionary containing the token's claims if valid.

        Raises:
            UnauthorizedException: If the token is invalid or validation fails for
                any reason.
        """
        logger.debug("Starting token validation")
        try:
            logger.debug(
                "Attempting validation with introspection "
                f"endpoint: {self.introspect_endpoint}"
            )
            return self._validate_with_introspection(token)
        except ValueError as e:
            logger.error(f"Token introspection failed: {e}")
            raise UnauthorizedException("Token validation failed") from e

    def _validate_with_introspection(self, token: str) -> dict[str, Any]:
        """Validates a token using the introspection endpoint."""
        data = {
            "token": token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        logger.debug(f"Making introspection request to {self.introspect_endpoint}")
        try:
            response = requests.post(self.introspect_endpoint, data=data, timeout=5)
            response.raise_for_status()
            token_info: dict[str, Any] = response.json()
            logger.debug(f"Introspection validation successful: {token_info}")
            return token_info
        except RequestException as e:
            logger.error(f"Token introspection request failed: {str(e)}")
            raise UnauthorizedException(
                f"Token introspection request failed: {e}"
            ) from e
