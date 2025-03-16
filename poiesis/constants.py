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
    """Constants for the Poiesis.

    Attributes:
        ENVIRONMENT: The environment in which the application is running.
    """

    ENVIRONMENT: Literal["dev", "prod"] = cast(
        Literal["dev", "prod"], os.environ.get("POIESIS_ENV", "dev")
    )

    @dataclass(frozen=True)
    class Database:
        """Constants for the database.

        Attributes:
            ENVIRONMENT: The environment in which the application is running.
        """

        @dataclass(frozen=True)
        class MongoDB:
            """Constants for the MongoDB database.

            Attributes:
                CONNECTION_STRING: The connection string for the MongoDB database.
                DATABASE: The name of the database to use.
                MAX_POOL_SIZE: The maximum number of connections to the database.
            """

            CONNECTION_STRING: str = os.environ.get(
                "MONGODB_CONNECTION_STRING", "mongodb://localhost:27017"
            )
            DATABASE: str = os.environ.get("MONGODB_DATABASE", "poiesis")
            MAX_POOL_SIZE: int = int(os.environ.get("MONGODB_MAX_POOL_SIZE", "10"))


@lru_cache
def get_poiesis_constants() -> PoesisConstants:
    """Get the Poiesis constants.

    Returns:
        PoesisConstants: The Poiesis constants.
    """
    return PoesisConstants()
