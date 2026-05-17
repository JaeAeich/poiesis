"""Content filer strategy — input-only.

Per the TES spec, `TesInput.content` carries the file body inline. There
is no output equivalent; the factory refuses to construct a content
output strategy.
"""

import logging

from poiesis.api.tes.models import TesInput
from poiesis.core.services.filer.strategy.filer_strategy import InputFilerStrategy

logger = logging.getLogger(__name__)


class ContentFilerStrategy(InputFilerStrategy):
    """Stage an inline `content` payload onto the PVC."""

    def __init__(self, payload: TesInput):
        """Initialise with the TES input carrying inline content."""
        super().__init__(payload)
        self.input = payload

    async def download_input_file(self, container_path: str) -> None:
        """Write `payload.content` directly to `container_path`."""
        if self.input.content is None:
            raise ValueError("Content is required for content filer strategy.")

        with open(container_path, "wb") as f:
            f.write(self.input.content.encode("utf-8"))

        logger.info("Created file with inline content at %s", container_path)

    async def download_input_directory(self, container_path: str) -> None:
        """Inline content has no directory equivalent; refuse."""
        raise NotImplementedError("Content filer does not support directory inputs.")
