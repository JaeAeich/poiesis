"""Filer strategy interfaces.

Two narrow interfaces — `InputFilerStrategy` and `OutputFilerStrategy` —
split out from a shared `BaseFilerStrategy` that carries the path-mapping
and glob helpers. Each concrete strategy implements only the interface(s)
its protocol actually supports:

The factory dispatches on (scheme, direction) and refuses combinations
the type system cannot satisfy.
"""

from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod
from glob import glob

from poiesis.api.tes.models import TesFileType, TesInput, TesOutput
from poiesis.core.constants import FILER_PVC_PATH

logger = logging.getLogger(__name__)


class BaseFilerStrategy:
    """Shared infrastructure for every filer strategy.

    Carries the path-mapping helpers (executor path → PVC-mounted path)
    and the glob utilities used by output strategies. Holds no abstract
    methods of its own — the input/output split is in the two
    subclasses.
    """

    def __init__(self, payload: TesInput | TesOutput):
        """Initialise with the TES input or output the strategy will handle."""
        self.payload = payload

    def _get_container_path(self, path: str) -> str:
        """Translate an executor-visible path to its PVC-mounted equivalent.

        Given a TES `/data/f1/file1`, returns `/transfer/f1/file1` so the
        filer pod can write to the PVC at the same logical location the
        executor will later read it from. Creates parents as a side effect.
        """
        container_path = os.path.join(FILER_PVC_PATH, path.lstrip("/"))
        os.makedirs(os.path.dirname(container_path), exist_ok=True)
        return container_path

    def _get_path_as_in_exec_pod(self, path: str) -> str:
        """Reverse of `_get_container_path` — PVC path → executor-visible path."""
        pvc_base = FILER_PVC_PATH
        if path.startswith(pvc_base):
            return "/" + path[len(pvc_base) :].lstrip("/")
        return path

    def _path_contains_glob(self, path: str) -> bool:
        """True if `path` contains any glob-significant character."""
        return any(char in path for char in "*?[]{}")

    def _infer_base_path(self, path: str) -> str:
        """Infer a `path_prefix` from a glob pattern.

        Used as a fallback when a TES client supplies a glob output path
        without an explicit `path_prefix`. Example: `/work/results/SRR*.fna`
        infers `/work/results/`.
        """
        if not self._path_contains_glob(path):
            return os.path.dirname(path)

        glob_pattern = re.compile(r"[\*\?\[\{]")
        match = glob_pattern.search(path)
        if not match:
            return os.path.dirname(path)

        pattern_start_index = match.start()
        last_slash_index = path.rfind("/", 0, pattern_start_index)
        return "/" if last_slash_index == -1 else path[: last_slash_index + 1]

    def _get_glob_files(self, container_path: str) -> list[tuple[str, str, bool]]:
        """Expand a glob path into `(path, relative_path, is_directory)` tuples.

        Each tuple's relative_path has the output's `path_prefix` stripped,
        ready to be appended to the destination URL. Each adapter's
        `upload_glob` decides how to map those tuples onto its protocol.
        """
        assert isinstance(self.payload, TesOutput)
        assert self.payload.path_prefix is not None
        results: list[tuple[str, str, bool]] = []
        for item in glob(container_path):
            relative = (
                self._get_path_as_in_exec_pod(item)
                .removeprefix(self.payload.path_prefix)
                .lstrip("/")
            )
            results.append((item, relative, os.path.isdir(item)))
        return results


class InputFilerStrategy(BaseFilerStrategy, ABC):
    """Strategy that can stage TES inputs onto the shared task volume."""

    @abstractmethod
    async def download_input_file(self, container_path: str) -> None:
        """Stage a single input file at `container_path`."""

    @abstractmethod
    async def download_input_directory(self, container_path: str) -> None:
        """Stage an input directory tree at `container_path`."""

    async def download(self) -> None:
        """Dispatch to file or directory download based on payload type."""
        container_path = self._get_container_path(self.payload.path)
        if self.payload.type == TesFileType.FILE:
            await self.download_input_file(container_path)
        else:
            await self.download_input_directory(container_path)


class OutputFilerStrategy(BaseFilerStrategy, ABC):
    """Strategy that can upload TES outputs from the shared task volume."""

    @abstractmethod
    async def upload_output_file(self, container_path: str) -> None:
        """Upload a single output file from `container_path`."""

    @abstractmethod
    async def upload_output_directory(self, container_path: str) -> None:
        """Upload an output directory tree from `container_path`."""

    @abstractmethod
    async def upload_glob(self, glob_files: list[tuple[str, str, bool]]) -> None:
        """Upload the `(path, relative_path, is_directory)` tuples from a glob.

        See `BaseFilerStrategy._get_glob_files` for the tuple shape.
        """

    async def upload(self) -> None:
        """Dispatch to glob, file, or directory upload.

        Glob upload is preferred when the path contains wildcards or the
        caller supplied a `path_prefix`. Falls back to uploading the
        parent directory when a glob matches no files.
        """
        assert isinstance(self.payload, TesOutput)
        is_glob_like = self._path_contains_glob(self.payload.path)
        container_path = self._get_container_path(self.payload.path)

        if self.payload.path_prefix or is_glob_like:
            if is_glob_like and not self.payload.path_prefix:
                inferred_prefix = self._infer_base_path(self.payload.path)
                logger.debug(
                    "Inferred path_prefix '%s' from path '%s'",
                    inferred_prefix,
                    self.payload.path,
                )
                self.payload.path_prefix = inferred_prefix

            assert self.payload.path_prefix is not None, (
                "path_prefix is required for glob operations "
                "but was not found or inferred."
            )

            globbed = self._get_glob_files(container_path)
            if globbed:
                logger.info(
                    "Found %d file(s) matching glob '%s'",
                    len(globbed),
                    self.payload.path,
                )
                logger.debug("Glob matched: %s", [item[0] for item in globbed])
                await self.upload_glob(globbed)
                return

            logger.warning(
                "Output glob '%s' matched no files; falling back to "
                "uploading parent directory '%s'.",
                self.payload.path,
                self.payload.path_prefix,
            )
            parent = self._get_container_path(self.payload.path_prefix)
            await self.upload_output_directory(parent)
            return

        if (
            self.payload.type == TesFileType.FILE
            and os.path.exists(container_path)
            and os.path.isfile(container_path)
        ):
            await self.upload_output_file(container_path)
            return

        if self.payload.type == TesFileType.FILE:
            logger.warning(
                "Output declared FILE but not found at %s; uploading as directory",
                container_path,
            )
        await self.upload_output_directory(container_path)
