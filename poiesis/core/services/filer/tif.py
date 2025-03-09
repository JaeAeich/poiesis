"""Entry point for the TIF service."""

import logging

from poiesis.api.tes.models import TesInput
from poiesis.core.ports.message_broker import Message
from poiesis.core.services.filer.filer import Filer
from poiesis.core.services.filer.filer_strategy_factory import FilerStrategyFactory

logger = logging.getLogger(__name__)


class Tif(Filer):
    """Task input filer.

    Args:
        name: Name of the task.
        inputs: List of task inputs.

    Attributes:
        name: Name of the task.
        inputs: List of task inputs.
        message_broker: Message broker.
    """

    def __init__(self, name: str, inputs: list[TesInput]) -> None:
        """Task input filer.

        Args:
            name: Name of the task.
            inputs: List of task inputs.

        Attributes:
            name: Name of the task.
            inputs: List of task inputs.
            message_broker: Message broker.
        """
        super().__init__()
        self.name = name
        self.inputs = inputs

    def file(self) -> None:
        """Filing logic, download."""
        for input in self.inputs:
            filer_strategy = FilerStrategyFactory.create_strategy(input.url)
            try:
                filer_strategy.download(input)
            except Exception as e:
                self.message(Message(f"TIF failed: {e}"))
                raise
