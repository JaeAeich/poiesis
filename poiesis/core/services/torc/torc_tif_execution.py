"""Create Tif Job and monitor it."""

import json
import logging

from kubernetes.client import (
    V1ObjectMeta,
)

from poiesis.api.tes.models import TesInput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.torc.torc_execution_template import TorcExecutionTemplate

core_constants = get_poiesis_core_constants()

logger = logging.getLogger(__name__)


class TorcTifExecution(TorcExecutionTemplate):
    """Tif execution class.

    This class is responsible for creating the Tif Job.

    Args:
        name: The name of the TES task will be modified for Tif Job.
        inputs: The list of inputs that Tif will create and monitor.

    Attributes:
        name: The name of the TES task will be modified for Tif Job.
        inputs: The list of inputs that Tif will create and monitor.
        message_broker: Message broker client.
        message: Message for the message broker which would to sent to TOrc.
        kubernetes_client: Kubernetes client.
    """

    def __init__(self, id: str, inputs: list[TesInput] | None) -> None:
        """Initialize the Tif execution class.

        Args:
            id: The id of the TES task.
            inputs: The list of inputs that Tif will create and monitor.

        Attributes:
            id: The id of the TES task.
            inputs: The list of inputs that Tif will create and monitor.
            message_broker: Message broker client.
            message: Message for the message broker which would to sent to TOrc.
            kubernetes_client: Kubernetes client.
        """
        super().__init__()
        self.id = id
        self.inputs = inputs

    async def start_job(self) -> None:
        """Create the K8s job for Tif."""
        tif_job_name = f"{core_constants.K8s.TIF_PREFIX}-{self.id}"
        inputs = (
            json.dumps([input.model_dump() for input in self.inputs])
            if self.inputs
            else "[]"
        )

        metadata = V1ObjectMeta(
            name=tif_job_name,
            labels={
                "service": core_constants.K8s.TIF_PREFIX,
                "name": tif_job_name,
                "parent": f"{core_constants.K8s.TORC_PREFIX}-{self.id}",
            },
        )

        commands: list[str] = ["poiesis", "tif", "run"]
        args: list[str] = ["--name", self.id, "--inputs", inputs]
        await self.create_job(self.id, tif_job_name, commands, args, metadata)
