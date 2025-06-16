"""Poiesis API constants."""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, cast

from poiesis.constants import get_poiesis_constants

constants = get_poiesis_constants()


@dataclass(frozen=True)
class PoiesisApiConstants:
    """Constants used in the Poiesis API.

    Attributes:
        SPEC_GIT_HASH: The git hash of the OpenAPI specification that the API uses.
            This refers to the git commit from where the specification was copied
            and then modified if needed without changing the TES specification.

            Note: The openAPI specification file is named as
                "<SPEC_GIT_HASH>.openapi.yaml", but it is not verbatim.
    """

    SPEC_GIT_HASH = "c4c17c9"
    TES_VERSION = "v1.1.0"
    BASE_PATH = "ga4gh/tes/v1"

    @dataclass(frozen=True)
    class Task:
        """Constants used in the Task."""

        NAME = "poiesis-tes-task"

    @dataclass(frozen=True)
    class Gunicorn:
        """Constants used in the Gunicorn server.

        Attributes:
            PORT: The port on which the Gunicorn server listens.
            WORKERS: The number of Gunicorn workers.
                Note: Defaults to the (number of CPU cores) * 2 + 1.
            TIMEOUT: The timeout for the Gunicorn server.
        """

        HOST = "0.0.0.0" if constants.ENVIRONMENT == "prod" else "127.0.0.1"  # nosec B104
        PORT = os.getenv("POIESIS_API_SERVER_PORT", "8000")
        WORKERS = os.getenv("POIESIS_UVICORN_WORKERS")
        TIMEOUT = os.getenv("POIESIS_UVICORN_TIMEOUT", "120")

    @dataclass(frozen=True)
    class Auth:
        """Constants used in the authentication.

        Attributes:
            AUTH: The authentication method.
        """

        AUTH: Literal["oauth2", "dummy"] = cast(
            Literal["oauth2", "dummy"], os.getenv("AUTH", "dummy")
        )

        @dataclass(frozen=True)
        class OAuth2:
            """Constants used in the generic OAuth2 / OpenID Connect client.

            Attributes:
                ISSUER: The OpenID Connect issuer URL.
                CLIENT_ID: The OAuth2 client identifier.
                TOKEN_ENDPOINT: URL to exchange credentials for tokens.
                USERINFO_ENDPOINT: URL to fetch authenticated user details.
                INTROSPECT_ENDPOINT: URL to validate tokens (optional).
                JWKS_URI: Public keys used to validate JWT tokens.
            """

            ISSUER = os.getenv("OAUTH2_ISSUER")
            CLIENT_ID = os.getenv("OAUTH2_CLIENT_ID")

            TOKEN_ENDPOINT = f"{ISSUER}/protocol/openid-connect/token"
            USERINFO_ENDPOINT = f"{ISSUER}/protocol/openid-connect/userinfo"
            INTROSPECT_ENDPOINT = f"{ISSUER}/protocol/openid-connect/token/introspect"
            JWKS_URI = f"{ISSUER}/protocol/openid-connect/certs"


@lru_cache
def get_poiesis_api_constants() -> PoiesisApiConstants:
    """Get the Poiesis API constants.

    Returns:
        PoiesisApiConstants: The Poiesis API constants.
    """
    return PoiesisApiConstants()
