"""Models used by the API.

These are extensions of the models defined in the TES API specification.
"""

from enum import Enum

from pydantic import BaseModel

from poiesis.api.tes.models import TesState


class TesView(Enum):
    """View of the task."""

    BASIC = "BASIC"
    FULL = "FULL"
    MINIMAL = "MINIMAL"


class MinimalTesTask(BaseModel):
    """Minimal task model."""

    id: str
    state: str


class TesListTasksFilter(BaseModel):
    """Filter for listing tasks."""

    name_prefix: str | None = None
    state: TesState | None = None
    tag_key: list[str] | None = None
    tag_value: list[str] | None = None
    view: TesView = TesView.MINIMAL
