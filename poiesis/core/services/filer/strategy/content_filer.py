"""Content filer strategy module."""

import logging
from typing import Optional

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy

core_constants = get_poiesis_core_constants()
logger = logging.getLogger(__name__)


class ContentFilerStrategy(FilerStrategy):
    """Content filer, if the content is given in the request."""

    def get_secrets(self, uri: Optional[str], path: str):
        """No need for secrets for content."""
        logger.info(f"No secrets needed for content filer with path: {path}")

    def check_permissions(self, uri: Optional[str], path: str):
        """Authentication is enough for content.

        Just check if the directory exists. No need for authorization checks.
        """
        logger.info(f"Checking permissions for content filer with path: {path}")

    async def download_input(self, _input: TesInput, container_path: str) -> None:
        """Get the content from request and mount to PVC.

        Args:
            _input: The input object from the TES task request.
            container_path: The path inside the container where the file needs to be
                downloaded to.
        """
        assert _input.content is not None

        content = _input.content.encode("utf-8")

        with open(container_path, "wb") as f:
            f.write(content)

        logger.info(f"Created file with content at {container_path}")

    async def upload_output(self, output: TesOutput, container_path: str) -> None:
        """Mount the content to PVC.

        Content filer does not support uploads according to TES spec.

        Args:
            output: The output object from the TES task request.
            container_path: The path inside the container from where the file needs to
                be uploaded from.
        """
        logger.error(
            f"Attempted to upload content from {container_path} which is not supported"
        )
        raise NotImplementedError(
            "Content filer does not support uploads according to TES spec."
        )
