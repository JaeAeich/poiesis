"""Poiesis API entrypoint placeholder.

The v1 API (connexion + Mongo handlers) was removed during the v2 cleanup.
The v2 API will be rebuilt on FastAPI + the asyncpg persistence layer; see
the v2 issue tracker for the slice that delivers it.

Importing this module currently raises so that any accidental wiring is loud.
"""

from typing import Any


def create_app() -> Any:
    """Placeholder until the FastAPI rewrite lands."""
    msg = (
        "Poiesis API is being rewritten on FastAPI as part of the v2 redesign. "
        "See the v2 issue tracker for the slice that delivers it."
    )
    raise NotImplementedError(msg)
