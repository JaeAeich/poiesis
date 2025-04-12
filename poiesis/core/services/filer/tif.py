"""Entry point for the TIF service."""

import logging

from poiesis.api.tes.models import TesInput
from poiesis.core.ports.message_broker import Message, MessageStatus
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

    async def file(self) -> None:
        """Filing logic, download.

        Raises:
            Exception: If the file cannot be downloaded.
        """
        for input in self.inputs:
            logger.info(f"Downloading {input.url} to {input.path}")
            filer_strategy = FilerStrategyFactory.create_strategy(input.url, input)
            logger.debug(f"Filer strategy: {filer_strategy.__class__.__name__}")
            try:
                await filer_strategy.download()
            except Exception as e:
                logger.error(f"Error downloading {input.url}: {str(e)}")
                self.message(
                    Message(status=MessageStatus.ERROR, message=f"TIF failed: {str(e)}")
                )
                raise
