"""Interface for TIF and TOF."""

import logging
import sys
from abc import ABC, abstractmethod

from poiesis.core import filer_error

logger = logging.getLogger(__name__)


class Filer(ABC):
    """Interface for TIF and TOF.

    The filer's exit code is the signal upstream: 0 on success, non-zero on
    failure. The TRec sidecar observes kubelet's recorded exit status via the
    Kubernetes API; no broker channel is required. A failing filer also
    leaves one line saying why in its termination message (`filer_error`).
    """

    async def execute(self) -> None:
        """Execute the filer.

        Returns on success (caller exits 0). On failure, writes the cause
        to the termination message and exits 1 — kubelet records both and
        TCtl reads them from `Pod.status`.
        """
        try:
            logger.info("Starting file operation")
            await self.transfer()
        except Exception as e:
            logger.exception("Filer failed")
            filer_error.record(e)
            sys.exit(1)
        logger.info("File operation completed successfully")

    @abstractmethod
    async def transfer(self) -> None:
        """Filing logic — upload or download."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the filer."""
