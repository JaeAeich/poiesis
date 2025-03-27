"""Filer strategy module."""

from abc import ABC, abstractmethod
from typing import Optional

from poiesis.api.tes.models import TesInput, TesOutput


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
    async def download_input(self, input: TesInput):
        """Download file from storage and mount to PVC.

        Args:
            input: The input object from the TES task request
        """
        pass

    @abstractmethod
    async def upload_output(self, output: TesOutput):
        """Upload file to storage created by executors, mounted to PVC.

        Args:
            output: The output object from the TES task request
        """
        pass

    async def download(self, input: TesInput):
        """Download file from storage and mount to PVC.

        Get the appropriate secrets, check permissions and download the file.

        Args:
            input: The input object from the TES task request
        """
        self.get_secrets(input.url, input.path)
        self.check_permissions(input.url, input.path)
        await self.download_input(input)

    async def upload(self, output: TesOutput):
        """Upload file to storage created by executors, mounted to PVC.

        Get the appropriate secrets, check permissions and upload the file.

        Args:
            output: The output object from the TES task request.
        """
        self.get_secrets(output.url, output.path)
        self.check_permissions(output.url, output.path)
        await self.upload_output(output)
