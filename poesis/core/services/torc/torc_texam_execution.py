"""Create Texam Job and monitor it."""

from typing import Optional

from poesis.api.tes.models import TesExecutor, TesResources
from poesis.core.services.torc.torc_execution_template import TorcExecutionTemplate


class TorcTexamExecution(TorcExecutionTemplate):
    """Tif execution class.

    This class is responsible for creating the Texam Job and monitoring it.

    Args:
        name: The name of the TES task will be modified for Texam Job.
        executors: The list of executors that Texam will create and monitor.
        resources: The resources that need to be allocated for the executors.
        volumes: The list of volumes that need to be mounted to the executors.

    Attributes:
        name: The name of the TES task will be modified for Texam Job.
        executors: The list of executors that Texam will create and monitor.
        resources: The resources that need to be allocated for the executors.
        volumes: The list of volumes that need to be mounted to the executors.
    """

    def __init__(
        self,
        name: str,
        executors: list[TesExecutor],
        resources: Optional[TesResources],
        volumes: Optional[list[str]],
    ):
        """Initialize the Tif execution class.

        Args:
            name: The name of the TES task will be modified for Texam Job.
            executors: The list of executors that Texam will create and monitor.
            resources: The resources that need to be allocated for the executors.
            volumes: The list of volumes that need to be mounted to the executors.

        Attributes:
            name: The name of the TES task will be modified for Texam Job.
            executors: The list of executors that Texam will create and monitor.
            resources: The resources that need to be allocated for the executors.
            volumes: The list of volumes that need to be mounted to the executors.
        """
        pass

    def start_job(self):
        """Create the K8s job for Texam."""
        pass
