"""Filer strategy module."""

import os
from abc import ABC, abstractmethod
from typing import Optional

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.utils import split_path_for_mounting

core_constants = get_poiesis_core_constants()


class FilerStrategy(ABC):
    """Filer strategy interface."""

    @abstractmethod
    def get_secrets(self, uri: Optional[str], path: str):
        """Get secrets if needed for the protocol.

        Args:
            uri: The URI of the file.
            path: The path in the storage.
        """
        pass

    @abstractmethod
    def check_permissions(self, uri: Optional[str], path: str):
        """Check if the user has the necessary permissions.

        User need to have correct read/write permissions to the file at
        the path mentioned in the URI.

        Args:
            uri: The URI of the file.
            path: The path of the storage.
        """
        pass

    @abstractmethod
    async def download_input(self, input: TesInput, container_path: str):
        """Download file from storage and mount to PVC.

        Args:
            input: The input object from the TES task request
            container_path: The path inside the container where the file needs to be
                downloaded which has been mounted to PVC accordingly.
        """
        pass

    @abstractmethod
    async def upload_output(self, output: TesOutput, container_path: str):
        """Upload file to storage created by executors, mounted to PVC.

        Args:
            output: The output object from the TES task request
            container_path: The path inside the container from where the file needs to
                be uploaded to the storage.
        """
        pass

    def _get_container_path(self, path: str) -> str:
        """Get the container path for the file.

        For each path say `/data/f1/f2/file1`, the container path will be
        `/transfer/f1/f2/file1`, this way this location can be mounted to PVC
        at `/data` path, retaining the original path structure, ie `/data/f1/f2/file1`.

        Args:
            path: The path of the file.
        """
        container_path = os.path.join(
            core_constants.K8s.FILER_PVC_PATH,
            split_path_for_mounting(path)[1].lstrip("/"),
        )
        os.makedirs(os.path.dirname(container_path), exist_ok=True)
        return container_path

    async def download(self, input: TesInput):
        """Download file from storage and mount to PVC.

        Get the appropriate secrets, check permissions and download the file.

        Args:
            input: The input object from the TES task request
        """
        self.get_secrets(input.url, input.path)
        self.check_permissions(input.url, input.path)
        container_path = self._get_container_path(input.path)
        await self.download_input(input, container_path)

    async def upload(self, output: TesOutput):
        """Upload file to storage created by executors, mounted to PVC.

        Get the appropriate secrets, check permissions and upload the file.

        Args:
            output: The output object from the TES task request.
        """
        self.get_secrets(output.url, output.path)
        self.check_permissions(output.url, output.path)
        container_path = self._get_container_path(output.path)
        await self.upload_output(output, container_path)
