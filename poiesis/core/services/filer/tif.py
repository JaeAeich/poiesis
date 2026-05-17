"""Entry point for the TIF service."""

import logging

from poiesis.api.tes.models import TesInput
from poiesis.core.services.filer.filer import Filer
from poiesis.core.services.filer.filer_strategy_factory import create_input_strategy

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
            logger.info("Downloading %s to %s", tes_input.url, tes_input.path)
            strategy = create_input_strategy(tes_input.url, tes_input)
            logger.debug("Filer strategy: %s", strategy.__class__.__name__)
            try:
                await strategy.download()
            except Exception:
                logger.exception("Error downloading %s", tes_input.url)
                raise
