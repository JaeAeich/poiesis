"""Create Tof Job and monitor it."""

from typing import Optional

from poesis.api.tes.models import TesOutput
from poesis.core.services.torc.torc_execution_template import TorcExecutionTemplate


class TorcTofExecution(TorcExecutionTemplate):
    """Tif execution class.

    This class is responsible for creating the Tof Job.

    Args:
        name: The name of the TES task will be modified for Tof Job.
        outputs: The list of outputs that Tof will create and monitor.
        volumes: The list of volumes that need to be mounted to the outputs.

    Attributes:
        name: The name of the TES task will be modified for Tof Job.
        outputs: The list of outputs that Tof will create and monitor.
        volumes: The list of volumes that need to be mounted to the outputs
    """

    def __init__(
        self,
        name: str,
        outputs: Optional[list[TesOutput]],
        volumes: Optional[list[str]],
    ):
        """Initialize the Tif execution class.

        Args:
            name: The name of the TES task will be modified for Tof Job.
            outputs: The list of outputs that Tof will create and monitor.
            volumes: The list of volumes that need to be mounted to the outputs.

        Attributes:
            name: The name of the TES task will be modified for Tof Job.
            outputs: The list of outputs that Tof will create and monitor.
            volumes: The list of volumes that need to be mounted to the outputs
        """
        pass

    def start_job(self, task_data):
        """Create the K8s job for Tif."""
        pass
