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

    def __init__(
        self, name: str, outputs: list[TesOutput], volumes: list[str] | None
    ) -> None:
        """Task output filer.

        Args:
            name: Name of the task.
            outputs: List of task outputs.
            volumes: List of task volumes.

        Attributes:
            name: Name of the task.
            outputs: List of task outputs.
            message_broker: Message broker
        """
        super().__init__()
        self._name = name
        self.outputs = outputs
        self.volumes = volumes

    @property
    def name(self) -> str:
        """Name of the filer."""
        return self._name

    async def file(self) -> None:
        """Filing logic, upload.

        Raises:
            Exception: If the file cannot be uploaded.
        """
        for output in self.outputs:
            filer_strategy = FilerStrategyFactory.create_strategy(output.url, output)
            try:
                logger.info(f"Uploading output: {output}")
                await filer_strategy.upload(self.volumes)
            except Exception as e:
                logger.error(f"TOF failed: {e}")
                self.message(Message(f"TOF failed: {e}"))
                raise
