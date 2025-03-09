"""Entry point for the TOF service."""

import logging

from poiesis.api.tes.models import TesOutput
from poiesis.core.ports.message_broker import Message
from poiesis.core.services.filer.filer import Filer
from poiesis.core.services.filer.filer_strategy_factory import FilerStrategyFactory

logger = logging.getLogger(__name__)


class Tof(Filer):
    """Task output filer.

    Args:
        name: Name of the task.
        outputs: List of task outputs.

    Attributes:
        name: Name of the task.
        outputs: List of task outputs.
        message_broker: Message broker
    """

    def __init__(self, name: str, outputs: list[TesOutput]) -> None:
        """Task output filer.

        Args:
            name: Name of the task.
            outputs: List of task outputs.

        Attributes:
            name: Name of the task.
            outputs: List of task outputs.
            message_broker: Message broker
        """
        super().__init__()
        self.name = name
        self.outputs = outputs

    def file(self) -> None:
        """Filing logic, upload."""
        for output in self.outputs:
            filer_strategy = FilerStrategyFactory.create_strategy(output.url)
            try:
                filer_strategy.upload(output)
            except Exception as e:
                self.message(Message(f"TOF failed: {e}"))
                raise
