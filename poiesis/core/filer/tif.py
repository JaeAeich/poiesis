"""Entry point for the TIF service."""

from __future__ import annotations

import logging
import os
import stat
from typing import TYPE_CHECKING

from poiesis.core.constants import FILER_PVC_PATH
from poiesis.core.filer.filer import Filer
from poiesis.core.filer.filer_strategy_factory import (
    create_input_strategy,
    input_url,
)
from poiesis.core.filer.strategy.filer_strategy import redact_url

if TYPE_CHECKING:
    from collections.abc import Sequence

    from poiesis.tes.models import TesInput

logger = logging.getLogger(__name__)


class Tif(Filer):
    """Task input filer.

    Args:
        name: Name of the task.
        inputs: List of task inputs.
        dirs: Executor paths of directories to create once the inputs are
            staged (see `make_task_dirs`).
    """

    def __init__(
        self, name: str, inputs: list[TesInput], dirs: Sequence[str] = ()
    ) -> None:
        """Task input filer."""
        super().__init__()
        self._name = name
        self.inputs = inputs
        self.dirs = list(dirs)

    @property
    def name(self) -> str:
        """Name of the filer."""
        return self._name

    async def transfer(self) -> None:
        """Filing logic — download inputs, then create the task's directories."""
        for tes_input in self.inputs:
            url = input_url(tes_input)
            logger.info("Downloading %s to %s", redact_url(url), tes_input.path)
            strategy = create_input_strategy(url, tes_input)
            logger.debug("Filer strategy: %s", strategy.__class__.__name__)
            try:
                await strategy.download()
            except Exception as e:
                logger.exception("Error downloading %s", redact_url(url))
                # Names the input in the cause the filer reports.
                e.add_note(f"input {tes_input.path}")
                raise
        make_task_dirs(self.dirs)


def make_task_dirs(paths: Sequence[str], root: str = FILER_PVC_PATH) -> None:
    """Create each executor path in `paths` as a directory under `root`.

    Like ``mkdir -p``, but each directory it creates gets the mode of `root`,
    the volume root, as the kubelet gives the mount points it creates:
    executors may run as another user than TIF and must be able to write
    there. Paths that exist are left as they are. A directory that can't be
    created is logged and skipped, not fatal: the executor may still
    create it.
    """
    if not paths:
        return
    mode = stat.S_IMODE(os.stat(root).st_mode)
    for path in paths:
        current = root
        try:
            for part in path.strip("/").split("/"):
                current = os.path.join(current, part)
                try:
                    os.mkdir(current)
                except FileExistsError:
                    continue
                os.chmod(current, mode)
            logger.info("Directory %s is ready", path)
        except OSError as exc:
            logger.warning("Could not create directory %s: %s", path, exc)
