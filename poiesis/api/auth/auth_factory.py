"""Factory for authentication providers."""

from poiesis.api.auth.providers.auth import AuthProvider
from poiesis.api.auth.providers.dummy import DummyAuthProvider
from poiesis.api.auth.providers.keycloak import KeycloakAuthProvider
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import InternalServerException

constants = get_poiesis_api_constants()


def get_auth_provider() -> AuthProvider:
    """Get the authentication provider."""
    if constants.Auth.AUTH == "dummy":
        return DummyAuthProvider()
    elif constants.Auth.AUTH == "keycloak":
        return KeycloakAuthProvider()
    else:
        raise InternalServerException(
            f"Invalid authentication method: {constants.Auth.AUTH}"
        )
