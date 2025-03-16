"""Interface controllers for the Poiesis API."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class InterfaceController(ABC):
    """Abstract base class for interface controllers."""

    @abstractmethod
    async def execute(self, *args: Any, **kwargs: Any) -> BaseModel:
        """Execute the interface controller."""
        pass
