"""OpenIDConnectAuthProvider."""

import logging
import os
from typing import Any

from authlib.integrations.httpx_client import OAuth2Client

from poiesis.api.auth.providers.auth import AuthProvider
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import InternalServerException, UnauthorizedException
from poiesis.api.utils import get_oidc_introspect_url

logger = logging.getLogger(__name__)
constants = get_poiesis_api_constants()


class OpenIDConnectAuthProvider(AuthProvider):
    """Generic OpenID Connect authentication provider."""

    def __init__(self):
        """Initialize the OpenIDConnectAuthProvider."""
        logger.debug("Initializing OpenIDConnectAuthProvider")
        if not getattr(constants.Auth.OIDC, "ISSUER", None) or not getattr(
            constants.Auth.OIDC, "CLIENT_ID", None
        ):
            logger.error("Missing required OIDC configuration")
            raise InternalServerException(
                "OIDC_ISSUER and OIDC_CLIENT_ID must be configured."
            )

        self.introspect_url = get_oidc_introspect_url()
        logger.debug(f"Using introspection URL: {self.introspect_url}")

        client_secret = os.getenv("OIDC_CLIENT_SECRET")
        if not client_secret:
            logger.error("OIDC_CLIENT_SECRET is not configured")
            raise InternalServerException("OIDC_CLIENT_SECRET is not configured")

        self.oidc_client = OAuth2Client(
            client_id=constants.Auth.OIDC.CLIENT_ID,
            client_secret=client_secret,
            server_metadata_url=constants.Auth.OIDC.DISCOVERY_URL,
        )
        logger.debug(
            f"OIDC client initialized with client_id: {constants.Auth.OIDC.CLIENT_ID}"
        )

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validates an OIDC ID token.

        This method checks the token's signature, issuer, audience, and expiration.

        Args:
            token: The JWT string to validate.

        Returns:
            A dictionary of the token's claims if validation is successful.

        Raises:
            InternalServerException: If the token is invalid.
        """
        try:
            token_data = self.oidc_client.introspect_token(
                url=self.introspect_url, token=token
            )
            data: dict[str, Any] = token_data.json()
            logger.debug(f"Token introspection response: {data}")

            if not data.get("active", False):
                logger.warning("OIDC token is not active")
                raise UnauthorizedException("OIDC token is not active")

            logger.debug("Token validation successful")
            return data
        except Exception as e:
            logger.error(f"OIDC token validation failed: {e}", exc_info=True)
            raise InternalServerException("OIDC token validation failed") from e
