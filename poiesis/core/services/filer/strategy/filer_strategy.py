"""Filer strategy module."""

import logging
import os
import re
from abc import ABC, abstractmethod
from glob import glob

from poiesis.api.tes.models import TesFileType, TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants

logger = logging.getLogger(__name__)

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
    async def upload_glob(self, glob_files: list[tuple[str, str, bool]]):
        """Upload files and directories when wildcards are present.

        Args:
            glob_files: List of tuples containing (file_path, relative_path,
                is_directory)
        """
        pass

    def _get_container_path(self, path: str) -> str:
        """Get the container path for the file.

        For each path say `/data/f1/f2/file1`, the container path will be
        `/transfer/f1/f2/file1`, this way this location can be mounted to PVC
        at `/data` path, retaining the original path structure, ie `/data/f1/f2/file1`.

        Note: This method creates the `container_path` if it doesn't exists.

        Args:
            path: The path of the file.
        """
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
        pvc_base = core_constants.K8s.FILER_PVC_PATH
        if path.startswith(pvc_base):
            return "/" + path[len(pvc_base) :].lstrip("/")
        return path

    async def download(self):
        """Download file from storage and mount to PVC.

        Get the appropriate secrets, check permissions and download the file.
        """
        container_path = self._get_container_path(self.payload.path)
        if self.payload.type == TesFileType.FILE:
            await self.download_input_file(container_path)
        else:
            await self.download_input_directory(container_path)

    def _get_glob_files(self, container_path: str) -> list[tuple[str, str, bool]]:
        """Get the list of the files and directories from wildcards.

        Note: tuple[0] is the path of the file/directory, tuple[1] is the path
            from which the prefix `path_prefix` have been removed, and tuple[2] is
            a boolean indicating if the item is a directory. Each protocol might
            handle that URL differently, hence each `upload_glob` method should
            take care of this URL based on its own implementation and requirement.

        Returns:
            list[tuple[str, str, bool]]: List of tuple of file/directory path, its
                prefix removed path that needs to be appended to url, and whether it's
                a directory.
        """
        assert isinstance(self.payload, TesOutput)
        assert self.payload.path_prefix is not None
        _ret: list[tuple[str, str, bool]] = []
        matched_items = glob(container_path)

        for item in matched_items:
            path_prefix = self.payload.path_prefix
            _file_path = (
                self._get_path_as_in_exec_pod(item)
                .removeprefix(path_prefix)
                .lstrip("/")
            )

            is_directory = os.path.isdir(item)
            _ret.append((item, _file_path, is_directory))

        return _ret

    def _path_contains_glob(self, path: str) -> bool:
        """Checks if a path string contains glob-like characters."""
        return any(char in path for char in "*?[]{}")

    def _infer_base_path(self, path: str) -> str:
        """Infers the base directory from a glob path.

        This is used as the 'path_prefix' for calculating
        relative upload paths. Fallback in case TES client
        doesn't provide path_prefix but still has a glob pattern.

        Example: '/work/results/SRR*.fna' -> '/work/results/'
        """
        if not self._path_contains_glob(path):
            return os.path.dirname(path)

        # Find the part of the path before the first wildcard.
        glob_pattern = re.compile(r"[\*\?\[\{]")
        match = glob_pattern.search(path)
        if not match:
            # Should be unreachable if _path_contains_glob is true, but defensive.
            return os.path.dirname(path)

        pattern_start_index = match.start()
        # Find the last directory separator before the pattern.
        last_slash_index = path.rfind("/", 0, pattern_start_index)

        return "/" if last_slash_index == -1 else path[: last_slash_index + 1]

    async def upload(self):
        """Upload file to storage created by executors, mounted to PVC.

        This method correctly dispatches to glob, file, or directory handlers
        and includes robust logging and fallback mechanisms.
        """
        assert isinstance(self.payload, TesOutput)
        is_glob_like = self._path_contains_glob(self.payload.path)
        container_path = self._get_container_path(self.payload.path)

        # Handle all glob-related operations first.
        if self.payload.path_prefix or is_glob_like:
            # Ensure a path_prefix exists, inferring if necessary for
            # non-compliant clients.
            if is_glob_like and not self.payload.path_prefix:
                inferred_prefix = self._infer_base_path(self.payload.path)
                logger.debug(
                    f"Inferred path_prefix '{inferred_prefix}' from "
                    f"path '{self.payload.path}'",
                )
                self.payload.path_prefix = inferred_prefix

            assert self.payload.path_prefix is not None, (
                "path_prefix is required for glob operations but was not found "
                "or inferred."
            )

            # Execute the glob and evaluate results.
            globbed_files = self._get_glob_files(container_path)

            if globbed_files:
                logger.info(
                    f"Found {len(globbed_files)} file(s) matching glob "
                    f"pattern '{self.payload.path}'.",
                )
                logger.debug(
                    "Glob matched files: %s", [item[0] for item in globbed_files]
                )
                await self.upload_glob(globbed_files)
            else:
                logger.warning(
                    f"Output glob pattern '{self.payload.path}' did not match any "
                    "files. Falling back to uploading the entire parent directory"
                    f"'{self.payload.path_prefix}'. This may indicate a "
                    "misconfiguration in the workflow definition.",
                )
                parent_dir_container_path = self._get_container_path(
                    self.payload.path_prefix
                )
                await self.upload_output_directory(parent_dir_container_path)

        # Handle standard file uploads.
        elif (
            self.payload.type == TesFileType.FILE
            and os.path.exists(container_path)
            and os.path.isfile(container_path)
        ):
            await self.upload_output_file(container_path)

        # Handle standard directory uploads.
        else:
            if self.payload.type == TesFileType.FILE:
                logger.warning(
                    "Output specified as file but not found at"
                    f"path: {container_path}. Assuming it to be"
                    "a directory.",
                )
            await self.upload_output_directory(container_path)
