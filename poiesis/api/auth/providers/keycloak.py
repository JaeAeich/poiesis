"""Keycloak authentication provider."""

import logging
import os
from http import HTTPStatus
from typing import Any

import jwt
import requests
from keycloak import KeycloakOpenID

from poiesis.api.auth.providers.auth import AuthProvider
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import InternalServerException, UnauthorizedException

logger = logging.getLogger(__name__)
constants = get_poiesis_api_constants()


class KeycloakAuthProvider(AuthProvider):
    """Keycloak authentication provider."""

    def __init__(
        self,
        server_url: str = constants.Auth.Keycloak.URL,
        realm_name: str = constants.Auth.Keycloak.REALM,
        client_id: str = constants.Auth.Keycloak.CLIENT_ID,
    ):
        """Initialize the Keycloak provider.

        Args:
            server_url: The Keycloak server URL
            realm_name: The Keycloak realm name
            client_id: The Keycloak client ID
        """
        self.server_url = server_url
        if not self.server_url:
            raise InternalServerException("Keycloak server URL not found")
        self.realm_name = realm_name
        self.client_id = client_id
        self.client_secret = os.getenv("KEYCLOAK_CLIENT_SECRET")
        if not self.client_secret:
            raise InternalServerException("Keycloak client secret not found")
        self.keycloak_openid = KeycloakOpenID(
            server_url=server_url,
            client_id=client_id,
            realm_name=realm_name,
            client_secret_key=self.client_secret,
        )
        self._public_key: str | None = None

    def get_public_key(self) -> str:
        """Get the public key for token validation."""
        if not self._public_key:
            try:
                url = f"{self.server_url.rstrip('/')}/realms/{self.realm_name}"
                response = requests.get(url, timeout=(3.0, 10.0))
                if response.status_code != HTTPStatus.OK:
                    logger.error(
                        "Failed to get realm info:"
                        f" {response.status_code}: {response.text}"
                    )
                    raise InternalServerException(
                        "Failed to get realm info from Keycloak:"
                        f" {response.status_code}"
                    )

                realm_info = response.json()
                public_key = realm_info.get("public_key")
                if not public_key:
                    raise InternalServerException("Public key not found in realm info")

                self._public_key = f"""-----BEGIN PUBLIC KEY-----
{public_key}
-----END PUBLIC KEY-----"""
                logger.info("Successfully retrieved public key from Keycloak")
            except Exception as e:
                logger.error(f"Failed to get public key: {e}")
                raise InternalServerException(
                    "Failed to get public key from Keycloak"
                ) from e
        return self._public_key

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validate a JWT token from Keycloak using PyJWT directly.

        Args:
            token: The JWT token to validate

        Returns:
            Dict containing token information if valid

        Raises:
            UnauthorizedException: If token is invalid
        """
        try:
            if token.startswith("Bearer "):
                token = token.replace("Bearer ", "")

            public_key = self.get_public_key()
            options = {
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": False,
            }
            token_info: dict[str, Any] = jwt.decode(
                token,
                public_key,
                algorithms=[constants.Auth.Keycloak.ALGORITHM],
                options=options,
            )
            return token_info
        except jwt.ExpiredSignatureError as e:
            logger.error("Token has expired")
            raise UnauthorizedException("Token has expired") from e
        except jwt.InvalidTokenError as e:
            logger.error(f"Invalid token: {e}")
            raise UnauthorizedException(f"Invalid token: {str(e)}") from e
        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            raise UnauthorizedException("Invalid or expired token") from e
