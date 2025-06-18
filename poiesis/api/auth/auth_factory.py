"""Factory for authentication providers."""

from poiesis.api.auth.providers.auth import AuthProvider
from poiesis.api.auth.providers.dummy import DummyAuthProvider
from poiesis.api.auth.providers.oidc import OpenIDConnectAuthProvider
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import InternalServerException

constants = get_poiesis_api_constants()


def get_auth_provider() -> AuthProvider:
    """Get the authentication provider."""
    auth_type = str(constants.Auth.AUTH).strip().lower()
    if auth_type == "dummy":
        return DummyAuthProvider()
    elif auth_type == "oidc":
        return OpenIDConnectAuthProvider()
    else:
        raise InternalServerException(f"Invalid authentication method: {auth_type}")
