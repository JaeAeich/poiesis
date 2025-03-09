"""Local filer strategy module."""

import logging
import os
import shutil
from urllib.parse import urlparse

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy

logger = logging.getLogger(__name__)

core_constants = get_poiesis_core_constants()


class LocalFilerStrategy(FilerStrategy):
    """Local filer strategy."""

    def get_secrets(self):
        """No need for secrets for local files."""
        pass

    def check_permissions(self):
        """Authentication is enough for local files.

        No need for authorization checks.
        """
        pass

    def download_input(self, _input: TesInput):
        """Download file from storage and mount to PVC.

        Args:
            _input: The input file to be downloaded
        """
        assert _input.url is not None, "Input URL is required for local filer."

        source_path = urlparse(_input.url).path
        container_path = os.path.join(
            core_constants.K8s.FILER_PVC_PATH, _input.path.lstrip("/")
        )

        if not os.path.exists(source_path):
            raise FileNotFoundError(f"File {source_path} not found.")

        os.makedirs(os.path.dirname(container_path), exist_ok=True)
        shutil.copy2(source_path, container_path)
        logger.info(f"Copied {source_path} to {container_path}")

    def upload_output(self, output: TesOutput):
        """Upload file to storage created by executors, mounted to PVC.

        Args:
            output: The output file to be uploaded.
        """
        assert output.url is not None, "Output URL is required for local filer."

        container_path = os.path.join(
            core_constants.K8s.FILER_PVC_PATH, output.path.lstrip("/")
        )
        destination_path = urlparse(output.url).path

        if not os.path.exists(container_path):
            raise FileNotFoundError(f"File {container_path} not found.")

        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        shutil.copy2(container_path, destination_path)
        logger.info(f"Copied {container_path} to {destination_path}")
