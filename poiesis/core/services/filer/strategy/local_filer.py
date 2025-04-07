"""Local filer strategy module."""

import logging
import os
import shutil
from typing import Optional
from urllib.parse import urlparse

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy

logger = logging.getLogger(__name__)

core_constants = get_poiesis_core_constants()


class LocalFilerStrategy(FilerStrategy):
    """Local filer strategy."""

    def get_secrets(self, url: Optional[str], path: str):
        """No need for secrets for local files."""
        logger.info(f"No secrets needed for local filer with path: {path}")

    def check_permissions(self, url: Optional[str], path: str):
        """Authentication is enough for local files.

        No need for authorization checks.
        """
        logger.info(f"No permissions check needed for local filer with path: {path}")

    async def download_input(self, _input: TesInput, container_path: str):
        """Download file from storage and mount to PVC.

        Args:
            _input: The input file to be downloaded
            container_path: The path inside the container where the file needs to be
                downloaded to.
        """
        logger.info(f"Starting local file download to {container_path}")
        assert _input.url is not None, "Input URL is required for local filer."

        source_path = urlparse(_input.url).path

        if not os.path.exists(source_path):
            logger.error(f"File {source_path} not found")
            raise FileNotFoundError(f"File {source_path} not found.")

        shutil.copy2(source_path, container_path)
        logger.info(f"Copied {source_path} to {container_path}")

    async def upload_output(self, output: TesOutput, container_path: str):
        """Dummy upload output.

        Local filer strategy does not need to upload anything as the file is already
        present in the container.

        Args:
            output: The output file to be uploaded.
            container_path: The path inside the container from where the file needs to
                be uploaded from.
        """
        logger.info(f"Starting local file upload from {container_path}")
        source_path = urlparse(output.url).path

        if not os.path.exists(source_path):
            logger.error(f"File {source_path} not found")
            raise FileNotFoundError(f"File {source_path} not found.")

        shutil.copy2(source_path, container_path)
        logger.info(f"Copied {source_path} to {container_path}")
