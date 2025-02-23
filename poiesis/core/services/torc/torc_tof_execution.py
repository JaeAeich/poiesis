"""Create Tof Job and monitor it."""

from typing import Optional

from poiesis.api.tes.models import TesOutput
from poiesis.core.services.torc.torc_execution_template import TorcExecutionTemplate


class TorcTofExecution(TorcExecutionTemplate):
    """Tif execution class.

    This class is responsible for creating the Tof Job.

    Args:
        name: The name of the TES task will be modified for Tof Job.
        outputs: The list of outputs that Tof will create and monitor.

    Attributes:
        name: The name of the TES task will be modified for Tof Job.
        outputs: The list of outputs that Tof will create and monitor.
    """

    def __init__(
        self,
        name: str,
        outputs: Optional[list[TesOutput]],
    ):
        """Initialize the Tif execution class.

        Args:
            name: The name of the TES task will be modified for Tof Job.
            outputs: The list of outputs that Tof will create and monitor.

        Attributes:
            name: The name of the TES task will be modified for Tof Job.
            outputs: The list of outputs that Tof will create and monitor.
        """
        pass

    def start_job(self, task_data):
        """Create the K8s job for Tif."""
        pass
