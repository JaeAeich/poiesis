"""Entry point for the TOF service."""

import logging

from poiesis.api.tes.models import TesOutput
from poiesis.core.services.filer.filer import Filer
from poiesis.core.services.filer.filer_strategy_factory import FilerStrategyFactory

logger = logging.getLogger(__name__)


class Tof(Filer):
    """Task output filer.

    Args:
        name: Name of the task.
        outputs: List of task outputs.
    """

    def __init__(self, name: str, outputs: list[TesOutput]) -> None:
        """Task output filer."""
        super().__init__()
        self._name = name
        self.outputs = outputs

    @property
    def name(self) -> str:
        """Name of the filer."""
        return self._name

    async def file(self) -> None:
        """Filing logic — upload outputs."""
        for output in self.outputs:
            filer_strategy = FilerStrategyFactory.create_strategy(output.url, output)
            try:
                logger.info(f"Uploading output: {output}")
                await filer_strategy.upload()
            except Exception:
                logger.exception("TOF failed")
                raise
