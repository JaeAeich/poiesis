"""Factory for authentication providers."""

from poiesis.api.auth.providers.auth import AuthProvider
from poiesis.api.auth.providers.keycloak import KeycloakAuthProvider
from poiesis.api.auth.providers.none import NoneAuthProvider
from poiesis.api.constants import get_poiesis_api_constants

constants = get_poiesis_api_constants()


def get_auth_provider() -> AuthProvider:
    """Get the authentication provider."""
    if constants.Auth.AUTH == "none":
        return NoneAuthProvider()
    elif constants.Auth.AUTH == "keycloak":
        return KeycloakAuthProvider()
    else:
        raise ValueError(f"Invalid authentication method: {constants.Auth.AUTH}")
