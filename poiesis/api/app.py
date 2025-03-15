"""Main module of the Poiesis API.

This module creates and configures the connexion app.
"""

from pathlib import Path

from connexion import AsyncApp
from connexion.resolver import RelativeResolver

from poiesis.api.constants import get_poiesis_api_constants

constants = get_poiesis_api_constants()


def create_app() -> AsyncApp:
    """Create the connexion app.

    Returns:
        AsyncApp: The connexion app.
    """
    openapi_spec_directory = Path(__file__).parent / "tes" / "spec"
    app = AsyncApp(
        __name__,
        specification_dir=openapi_spec_directory,
    )

    app.add_api(
        f"{constants.SPEC_GIT_HASH}.openapi.yaml",
        resolver=RelativeResolver("poiesis.api.controllers"),
        validate_responses=True,
    )

    return app


app = create_app()
