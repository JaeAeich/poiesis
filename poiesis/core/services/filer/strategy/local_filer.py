"""Local filer strategy module."""

import logging
import os
import shutil
from pathlib import Path

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.services.filer.file_urls import resolve_file_url
from poiesis.core.services.filer.strategy.filer_strategy import (
    InputFilerStrategy,
    OutputFilerStrategy,
)

logger = logging.getLogger(__name__)


class LocalFilerStrategy(InputFilerStrategy, OutputFilerStrategy):
    """Local-filesystem filer strategy — handles both inputs and outputs."""

    def __init__(self, payload: TesInput | TesOutput) -> None:
        """Initialize the local filer strategy.

        Args:
            payload: The payload to instantiate the strategy implementation.
        """
        super().__init__(payload)
        self.input = self.payload if isinstance(self.payload, TesInput) else None
        self.output = self.payload if isinstance(self.payload, TesOutput) else None

    async def download_input_file(self, container_path: str) -> None:
        """Download file from storage and mount to PVC."""
        logger.info(f"Starting local file download to {container_path}")
        assert self.input
        assert self.input.url
        source_path = resolve_file_url(self.input.url)
        self._copy_file(source_path, container_path)

    async def download_input_directory(self, container_path: str) -> None:
        """Download input directory from a local path."""
        logger.info(f"Starting local directory download to {container_path}")
        assert self.input
        assert self.input.url
        source_path = resolve_file_url(self.input.url)
        self._copy_directory(source_path, container_path)

    async def upload_output_file(self, container_path: str) -> None:
        """Dummy upload output (local)."""
        logger.info(f"Starting local file upload from {container_path}")
        assert self.output
        assert self.output.url
        destination_path = resolve_file_url(self.output.url)
        self._copy_file(container_path, destination_path)
        self._record_upload(container_path, Path(destination_path).as_uri())

    async def upload_output_directory(self, container_path: str) -> None:
        """Upload output directory to a local path."""
        logger.info(f"Starting local directory upload from {container_path}")
        assert self.output
        assert self.output.url
        destination_path = resolve_file_url(self.output.url)
        self._copy_directory(container_path, destination_path)
        self._record_directory(container_path, destination_path)

    async def upload_glob(self, glob_files: list[tuple[str, str, bool]]) -> None:
        """Upload files and directories using wildcard pattern.

        Args:
            glob_files: List of tuples containing (file_path, relative_path,
                is_directory)
        """
        assert self.output is not None

        for file_path, relative_path, is_directory in glob_files:
            assert self.output
            assert self.output.url
            destination_base = resolve_file_url(self.output.url)
            destination_path = os.path.join(destination_base, relative_path)

            if is_directory:
                logger.warning(
                    f"Glob pattern matched directory '{file_path}' - uploading as"
                    f"directory (this may not be the intended behavior)"
                )
                # Ensure the destination directory exists
                os.makedirs(destination_path, exist_ok=True)
                # Copy directory contents recursively
                self._copy_directory(file_path, destination_path)
                self._record_directory(file_path, destination_path)
            else:
                # Ensure the destination directory exists
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                logger.info(f"Uploading file {file_path} to {destination_path}")
                self._copy_file(file_path, destination_path)
                self._record_upload(file_path, Path(destination_path).as_uri())

    def _record_directory(self, src: str, dst: str) -> None:
        """Record each file under `src` as uploaded to the same path under `dst`."""
        for root, _, files in os.walk(src):
            for name in files:
                path = os.path.join(root, name)
                target = os.path.join(dst, os.path.relpath(path, src))
                self._record_upload(path, Path(target).as_uri())

    def _copy_file(self, src: str, dst: str) -> None:
        """Copy a file from src to dst with validation."""
        if not os.path.exists(src):
            logger.error(f"File {src} not found")
            raise FileNotFoundError(f"File {src} not found.")
        if not os.path.isfile(src):
            logger.error(f"Source path {src} is not a file")
            raise IsADirectoryError(f"Source path {src} is not a file.")
        shutil.copy2(src, dst)
        logger.info(f"Copied file from {src} to {dst}")

    def _copy_directory(self, src: str, dst: str) -> None:
        """Copy a directory from src to dst with validation."""
        if not os.path.exists(src):
            logger.error(f"Directory {src} not found")
            raise FileNotFoundError(f"Directory {src} not found.")
        if not os.path.isdir(src):
            logger.error(f"Source path {src} is not a directory")
            raise NotADirectoryError(f"Source path {src} is not a directory.")
        shutil.copytree(src, dst, dirs_exist_ok=True)
        logger.info(f"Copied directory from {src} to {dst}")
