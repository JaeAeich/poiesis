"""Entry point for the TIF service."""

import logging

from poiesis.api.tes.models import TesInput
from poiesis.core.services.filer.filer import Filer
from poiesis.core.services.filer.filer_strategy_factory import FilerStrategyFactory

logger = logging.getLogger(__name__)


class Tif(Filer):
    """Task input filer.

    Args:
        name: Name of the task.
        inputs: List of task inputs.
    """

    def __init__(self, name: str, inputs: list[TesInput]) -> None:
        """Task input filer."""
        super().__init__()
        self._name = name
        self.inputs = inputs

    @property
    def name(self) -> str:
        """Name of the filer."""
        return self._name

    async def file(self) -> None:
        """Filing logic — download inputs."""
        for tes_input in self.inputs:
            logger.info(f"Downloading {tes_input.url} to {tes_input.path}")
            filer_strategy = FilerStrategyFactory.create_strategy(
                tes_input.url, tes_input
            )
            logger.debug(f"Filer strategy: {filer_strategy.__class__.__name__}")
            try:
                await filer_strategy.download()
            except Exception:
                logger.exception(f"Error downloading {tes_input.url}")
                raise
