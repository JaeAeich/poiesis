"""Create Tif Job and monitor it."""

from typing import Optional

from poesis.api.tes.models import TesInput
from poesis.core.services.torc.torc_execution_template import TorcExecutionTemplate


class TorcTifExecution(TorcExecutionTemplate):
    """Tif execution class.

    This class is responsible for creating the Tif Job.

    Args:
        name: The name of the TES task will be modified for Tif Job.
        inputs: The list of inputs that Tif will create and monitor.
        volumes: The list of volumes that need to be mounted to the inputs.

    Attributes:
        name: The name of the TES task will be modified for Tif Job.
        inputs: The list of inputs that Tif will create and monitor.
        volumes: The list of volumes that need to be mounted to the inputs.
    """

    def __init__(
        self, name: str, inputs: Optional[list[TesInput]], volumes: Optional[list[str]]
    ):
        """Initialize the Tif execution class.

        Args:
            name: The name of the TES task will be modified for Tif Job.
            inputs: The list of inputs that Tif will create and monitor.
            volumes: The list of volumes that need to be mounted to the inputs.

        Attributes:
            name: The name of the TES task will be modified for Tif Job.
            inputs: The list of inputs that Tif will create and monitor.
            volumes: The list of volumes that need to be mounted to the inputs.
        """
        pass

    def start_job(self):
        """Create the K8s job for Tif."""
        pass
