"""Entry point for the TOF service."""

import logging
import os

from poiesis.api.tes.models import TesFileType, TesOutput
from poiesis.core.filer_error import MissingOutputError
from poiesis.core.services.filer.filer import Filer
from poiesis.core.services.filer.filer_strategy_factory import create_output_strategy
from poiesis.core.services.filer.strategy import filer_strategy
from poiesis.core.services.filer.strategy.filer_strategy import redact_url

logger = logging.getLogger(__name__)


class Tof(Filer):
    """Task output filer.

    Args:
        name: Name of the task.
        outputs: List of task outputs.
    """

    def __init__(self, name: str, outputs: list[TesOutput]) -> None:
        """Task output filer."""
        super().__init__()
        self._name = name
        self.outputs = outputs

    @property
    def name(self) -> str:
        """Name of the filer."""
        return self._name

    async def file(self) -> None:
        """Filing logic — upload outputs."""
        for output in self.outputs:
            if output.url is None:
                raise ValueError("output.url is required for TOF")
            strategy = create_output_strategy(output.url, output)
            try:
                logger.info(
                    "Uploading output: %s",
                    output.model_copy(update={"url": redact_url(output.url)}),
                )
                await strategy.upload()
            except Exception as e:
                logger.exception("TOF failed")
                missing = _missing_output(output) if _is_not_found(e) else None
                if missing is not None:
                    raise MissingOutputError(missing) from e
                # Names the output in the cause the filer reports.
                e.add_note(f"output {output.path}")
                raise


def _is_not_found(error: Exception) -> bool:
    """True if `error` is how a strategy reports a path that isn't there."""
    return isinstance(error, FileNotFoundError | NotADirectoryError)


def _missing_output(output: TesOutput) -> str | None:
    """Say what is missing if `output` isn't on the task's volume as declared.

    The executors didn't produce such an output, so the failed upload is the
    user's error, not the system's. Returns None if the output is there:
    the upload then failed for another reason. A glob that matches nothing
    isn't missing; the strategy uploads nothing for it and succeeds.
    """
    if any(char in output.path for char in "*?[]{}"):
        return None
    path = os.path.join(filer_strategy.FILER_PVC_PATH, output.path.lstrip("/"))
    if not os.path.exists(path):
        return f"output {output.path} was not produced by the executors"
    if output.type == TesFileType.DIRECTORY and not os.path.isdir(path):
        return f"output {output.path} is declared a DIRECTORY but is not one"
    return None
