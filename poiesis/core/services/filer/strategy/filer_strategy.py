"""Filer strategy module."""

import os
from abc import ABC, abstractmethod
from glob import glob
from pathlib import Path

from poiesis.api.tes.models import TesFileType, TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.utils import split_path_for_mounting

core_constants = get_poiesis_core_constants()


class FilerStrategy(ABC):
    """Filer strategy interface."""

    def __init__(self, payload: TesInput | TesOutput):
        """Initialize the filer strategy.

        Args:
            payload: input or output object from the TES task request.
        """
        self.payload = payload

    @abstractmethod
    async def download_input_file(self, container_path: str):
        """Download file from storage and mount to PVC.

        Args:
            container_path: The path inside the container from where the file needs to
                be downloaded to the storage.
        """
        pass

    @abstractmethod
    async def download_input_directory(self, container_path: str):
        """Download the directory content from storage and mount to PVC.

        Args:
            container_path: The path inside the container from where the file needs to
                be downloaded to the storage.
        """
        pass

    @abstractmethod
    async def upload_output_file(self, container_path: str):
        """Upload file to storage created by executors, mounted to PVC.

        Args:
            container_path: The path inside the container from where the file needs to
                be uploaded to the storage.
        """
        pass

    @abstractmethod
    async def upload_output_directory(self, container_path: str):
        """Upload directory to storage created by executors, mounted to PVC.

        Args:
            container_path: The path inside the container from where the file needs to
                be uploaded to the storage.
        """
        pass

    @abstractmethod
    async def upload_glob(self, glob_files: list[tuple[str, str]]):
        """Upload files when wildcards are present."""
        pass

    def _get_container_path(self, path: str, volumes: list[str] | None = None) -> str:
        """Get the container path for the file.

        For each path say `/data/f1/f2/file1`, the container path will be
        `/transfer/f1/f2/file1`, this way this location can be mounted to PVC
        at `/data` path, retaining the original path structure, ie `/data/f1/f2/file1`.

        Note: This method creates the `container_path` if it doesn't exists.

        Args:
            path: The path of the file.
            volumes: The list of volumes.
        """
        for volume in volumes or []:
            if path.strip("/").startswith(volume.strip("/")):
                return path

        container_path = os.path.join(
            core_constants.K8s.FILER_PVC_PATH,
            path.lstrip("/"),
        )
        os.makedirs(os.path.dirname(container_path), exist_ok=True)
        return container_path

    def _get_path_as_in_exec_pod(self, path: str) -> str:
        """Get the path of the file as it was in exec pod.

        Note: This is done because file structure mounted in the filer pod
            is different from that of the executor pod.

        Args:
            path: The string path obtained from glob.

        Returns:
            str: Path of the file as it was in the executor path.
        """
        _path_without_pvc_base: str = path.removeprefix(
            core_constants.K8s.FILER_PVC_PATH
        )
        _reconstructed_path_as_in_exec_pod = Path(
            split_path_for_mounting(self.payload.path)[0]
        ).joinpath(_path_without_pvc_base.lstrip("/"))
        return str(_reconstructed_path_as_in_exec_pod)

    async def download(self):
        """Download file from storage and mount to PVC.

        Get the appropriate secrets, check permissions and download the file.
        """
        container_path = self._get_container_path(self.payload.path)
        if self.payload.type == TesFileType.FILE:
            await self.download_input_file(container_path)
        else:
            await self.download_input_directory(container_path)

    def _get_glob_files(self, container_path: str) -> list[tuple[str, str]]:
        """Get the list of the files from wildcards.

        Note: tuple[0] is the path of the file, while tuple[1] is the path
            from which the prefix `path_prefix` have been removed, since each
            protocol might handle that URL differently, hence each `upload_glob`
            method should take care of this URL based on its own implementation and
            requirement.

        Returns:
            list[tuple[str, str]]: List of tuple of file path of and its prefix removed
                path that needs to be appended to url.
        """
        assert isinstance(self.payload, TesOutput)
        assert self.payload.path_prefix is not None
        _ret: list[tuple[str, str]] = []
        files = glob(container_path)
        for file in files:
            path_prefix = self.payload.path_prefix
            _file_path = (
                self._get_path_as_in_exec_pod(file)
                .removeprefix(path_prefix)
                .lstrip("/")
            )
            _ret.append((file, _file_path))

        return _ret

    async def upload(self, volumes: list[str] | None):
        """Upload file to storage created by executors, mounted to PVC.

        Get the appropriate secrets, check permissions and upload the file.
        """
        container_path = self._get_container_path(self.payload.path, volumes)
        if isinstance(self.payload, TesOutput) and self.payload.path_prefix:
            await self.upload_glob(self._get_glob_files(container_path))
        elif self.payload.type == TesFileType.FILE:
            await self.upload_output_file(container_path)
        else:
            await self.upload_output_directory(container_path)
