"""Content filer strategy module."""

import logging

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy

core_constants = get_poiesis_core_constants()
logger = logging.getLogger(__name__)


class ContentFilerStrategy(FilerStrategy):
    """Content filer, if the content is given in the request."""

    def __init__(self, payload: TesInput | TesOutput):
        """Initialize the content filer strategy.

        Args:
            payload: The payload to instantiate the strategy
                implementation.
        """
        super().__init__(payload)
        self.input = self.payload if isinstance(self.payload, TesInput) else None
        self.output = self.payload if isinstance(self.payload, TesOutput) else None

    async def download_input_file(self, container_path: str) -> None:
        """Get the content from request and mount to PVC.

        Args:
            container_path: The path inside the container where the file needs to be
                downloaded to.
        """
        assert self.input is not None

        if self.input.content is None:
            raise ValueError("Content is required for content filer strategy.")

        content = self.input.content.encode("utf-8")

        with open(container_path, "wb") as f:
            f.write(content)

        logger.info(f"Created file with content at {container_path}.")

    async def download_input_directory(self, container_path: str):
        """Download input directory.

        Raises:
            NotImplementedError: Content filer doesn't support downloading
                directories.
        """
        raise NotImplementedError(
            "Content filer doesn't support downloading directories."
        )

    async def upload_output_file(self, container_path: str) -> None:
        """Mount the content to PVC.

        Content filer does not support uploads according to TES spec.

        Args:
            container_path: The path inside the container from where the file needs to
                be uploaded from.
        """
        logger.error(
            f"Attempted to upload content from {container_path} which is not supported"
        )
        raise NotImplementedError(
            "Content filer does not support uploads according to TES spec."
        )

    async def upload_output_directory(self, container_path: str):
        """Upload output dir.

        Raises:
            NotImplementedError: Content filer doesn't support uploading directories.
        """
        raise NotImplementedError(
            "Content filer does not support uploads according to TES spec."
        )

    async def upload_glob(self, glob_files: list[tuple[str, str, bool]]):
        """Upload output dir.

        Raises:
            NotImplementedError: Content filer doesn't support uploading directories.
        """
        raise NotImplementedError(
            "Content filer does not support uploads according to TES spec."
        )
