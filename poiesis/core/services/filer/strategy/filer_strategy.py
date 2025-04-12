"""Filer strategy module."""

import os
from abc import ABC, abstractmethod
from typing import Union

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.utils import split_path_for_mounting

core_constants = get_poiesis_core_constants()


class FilerStrategy(ABC):
    """Filer strategy interface."""

    def __init__(self, payload: Union[TesInput, TesOutput]):
        """Initialize the filer strategy.

        Args:
            payload: input or output object from the TES task request.
        """
        self.payload = payload

    @abstractmethod
    def get_secrets(self):
        """Get secrets if needed for the protocol."""
        pass

    @abstractmethod
    def check_permissions(self):
        """Check if the user has the necessary permissions."""
        pass

    @abstractmethod
    async def download_input(self, container_path: str):
        """Download file from storage and mount to PVC.

        Args:
            container_path: The path inside the container from where the file needs to
                be downloaded to the storage.
        """
        pass

    @abstractmethod
    async def upload_output(self, container_path: str):
        """Upload file to storage created by executors, mounted to PVC.

        Args:
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

    async def download(self):
        """Download file from storage and mount to PVC.

        Get the appropriate secrets, check permissions and download the file.
        """
        self.get_secrets()
        self.check_permissions()
        container_path = self._get_container_path(self.payload.path)
        await self.download_input(container_path)

    async def upload(self):
        """Upload file to storage created by executors, mounted to PVC.

        Get the appropriate secrets, check permissions and upload the file.
        """
        self.get_secrets()
        self.check_permissions()
        container_path = self._get_container_path(self.payload.path)
        await self.upload_output(container_path)
