"""OpenIDConnectAuthProvider."""

import logging
import os
import threading
from typing import Any

import jwt
from authlib.integrations.httpx_client import OAuth2Client
from jwt import InvalidTokenError, PyJWKClient

from poiesis.api.auth.providers.auth import AuthProvider
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import InternalServerException, UnauthorizedException
from poiesis.api.utils import get_oidc_introspect_url, get_oidc_jwks_uri

logger = logging.getLogger(__name__)
constants = get_poiesis_api_constants()


class SingletonMeta(type):
    """Singleton metaclass for OpenIDConnectAuthProvider."""

    _instances: dict[type, "OpenIDConnectAuthProvider"] = {}
    _lock = threading.Lock()

    def __call__(cls, *args: Any, **kwargs: Any) -> "OpenIDConnectAuthProvider":
        """Create a singleton instance of OpenIDConnectAuthProvider."""
        with cls._lock:
            if cls not in cls._instances:
                cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class OpenIDConnectAuthProvider(AuthProvider, metaclass=SingletonMeta):
    """Generic OpenID Connect authentication provider."""

    _oidc_client: OAuth2Client | None = None
    _introspect_url: str | None = None

    def __init__(self):
        """Initialize the OpenIDConnectAuthProvider singleton."""
        if getattr(self, "_initialized", False):
            return

        logger.debug("Initializing OpenIDConnectAuthProvider singleton")
        if not getattr(constants.Auth.OIDC, "ISSUER", None) or not getattr(
            constants.Auth.OIDC, "CLIENT_ID", None
        ):
            logger.error("Missing required OIDC configuration")
            raise InternalServerException(
                "OIDC_ISSUER and OIDC_CLIENT_ID must be configured."
            )

        if not OpenIDConnectAuthProvider._introspect_url:
            OpenIDConnectAuthProvider._introspect_url = get_oidc_introspect_url()
            logger.debug(
                f"Using introspection URL: {OpenIDConnectAuthProvider._introspect_url}"
            )

        client_secret = os.getenv("OIDC_CLIENT_SECRET")
        if not client_secret:
            logger.error("OIDC_CLIENT_SECRET is not configured")
            raise InternalServerException("OIDC_CLIENT_SECRET is not configured")

        # Initialize the OAuth2Client singleton if not already done
        if OpenIDConnectAuthProvider._oidc_client is None:
            OpenIDConnectAuthProvider._oidc_client = OAuth2Client(
                client_id=constants.Auth.OIDC.CLIENT_ID,
                client_secret=client_secret,
                server_metadata_url=constants.Auth.OIDC.DISCOVERY_URL,
            )
            logger.debug(
                "OIDC client initialized with "
                f"client_id: {constants.Auth.OIDC.CLIENT_ID}"
            )
        else:
            logger.debug(
                "OIDC client already initialized with "
                f"client_id: {constants.Auth.OIDC.CLIENT_ID}"
            )

        self.oidc_client = OpenIDConnectAuthProvider._oidc_client
        self.introspect_url = OpenIDConnectAuthProvider._introspect_url
        self._initialized = True

    def _validate_token_local(self, token: str) -> dict[str, Any]:
        """Locally validate a JWT using the provider's JWKS."""
        try:
            jwks_uri = get_oidc_jwks_uri()
            jwk_client = PyJWKClient(jwks_uri)
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            data = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512"],
                audience=constants.Auth.OIDC.CLIENT_ID,
                issuer=constants.Auth.OIDC.ISSUER,
                options={"verify_exp": True, "verify_aud": True, "verify_iss": True},
            )
            if not isinstance(data, dict):
                raise InternalServerException(
                    "Decoded JWT payload is not a dictionary."
                )
            logger.debug(f"Local JWT validation successful: {data}")
            return data
        except InvalidTokenError as e:
            logger.warning(f"Local JWT validation failed: {e}")
            raise UnauthorizedException(f"Invalid JWT: {e}") from e
        except Exception as e:
            logger.error(
                f"Unexpected error during local JWT validation: {e}", exc_info=True
            )
            raise InternalServerException("Local JWT validation failed") from e

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validates an OIDC ID token.

        This method checks the token's signature, issuer, audience, and expiration.
        Tries local validation first, falls back to introspection if needed.
        """
        try:
            return self._validate_token_local(token)
        except UnauthorizedException as e:
            logger.warning(
                f"Falling back to introspection due to local validation failure: {e}"
            )
        except Exception as e:
            logger.error(f"Local validation failed unexpectedly: {e}", exc_info=True)

        # Fallback to introspection
        try:
            data: dict[str, Any] = self.oidc_client.introspect_token(
                url=self.introspect_url, token=token
            ).json()
            logger.debug(f"Token introspection response: {data}")

            if not data.get("active", False):
                logger.warning("OIDC token is not active")
                raise UnauthorizedException("OIDC token is not active")

            logger.debug("Token validation successful (via introspection)")
            return data
        except Exception as e:
            logger.error(f"OIDC token validation failed: {e}", exc_info=True)
            raise InternalServerException("OIDC token validation failed") from e
