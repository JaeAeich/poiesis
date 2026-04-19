"""Constants for the Poiesis.

Contains constants used throughout the Poiesis application.
Much more general than the constants in the core or api modules.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, cast


@dataclass(frozen=True)
class PoesisConstants:
    """Top-level Poiesis constants.

    Attributes:
        ENVIRONMENT: The environment in which the application is running.
        LOG_LEVEL: Logger level.
    """

    ENVIRONMENT: Literal["dev", "prod"] = cast(
        "Literal['dev', 'prod']", os.environ.get("POIESIS_ENV", "dev")
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = cast(
        "Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']", os.getenv("LOG_LEVEL", "INFO")
    )


@lru_cache
def get_poiesis_constants() -> PoesisConstants:
    """Get the Poiesis constants.

    Returns:
        PoesisConstants: The Poiesis constants.
    """
    return PoesisConstants()
