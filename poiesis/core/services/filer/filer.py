"""Interface for TIF and TOF."""

import logging
import sys
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class Filer(ABC):
    """Interface for TIF and TOF.

    The filer's exit code is the only signal upstream: 0 on success, non-zero on
    failure. The TRec sidecar observes kubelet's recorded exit status via the
    Kubernetes API; no broker channel is required.
    """

    async def execute(self) -> None:
        """Execute the filer.

        Returns on success (caller exits 0). On failure, exits 1 — kubelet
        records the non-zero exit and TRec reads it from `Pod.status`.
        """
        try:
            logger.info("Starting file operation")
            await self.file()
        except Exception:
            logger.exception("Filer failed")
            sys.exit(1)
        logger.info("File operation completed successfully")

    @abstractmethod
    async def file(self) -> None:
        """Filing logic — upload or download."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the filer."""
