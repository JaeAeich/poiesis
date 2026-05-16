"""Constants for Poiesis.

Top-level constants used across the application. More general than the
constants in core or api modules.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, cast


@dataclass(frozen=True)
class PoesisConstants:
    """Top-level Poiesis constants.

    Attributes:
        LOG_LEVEL: Logger level.
    """

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = cast(
        "Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']", os.getenv("LOG_LEVEL", "INFO")
    )


@lru_cache
def get_poiesis_constants() -> PoesisConstants:
    """Get the Poiesis constants."""
    return PoesisConstants()
