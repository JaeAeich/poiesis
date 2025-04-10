"""Models used by the API.

These are extensions of the models defined in the TES API specification.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


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

    name_prefix: Optional[str] = None
    state: Optional[str] = None
    tag_key: Optional[list[str]] = None
    tag_value: Optional[list[str]] = None
    view: TesView = TesView.MINIMAL
