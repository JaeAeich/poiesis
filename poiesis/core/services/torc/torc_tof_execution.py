"""Create TOF Job and monitor it."""

import logging

from kubernetes.client import (
    V1ObjectMeta,
)

from poiesis.api.tes.models import TesOutput
from poiesis.core.constants import get_labels, get_poiesis_core_constants
from poiesis.core.services.torc.torc_execution_template import TorcExecutionTemplate

core_constants = get_poiesis_core_constants()

logger = logging.getLogger(__name__)


class TorcTofExecution(TorcExecutionTemplate):
    """TOF execution class.

    This class is responsible for creating the Tof Job.

    Args:
        name: The name of the TES task will be modified for TOF Job.
        outputs: The list of outputs that Tof will create and monitor.

    Attributes:
        name: The name of the TES task will be modified for TOF Job.
        outputs: The list of outputs that TOF will create and monitor.
        message_broker: Message broker client.
        message: Message for the message broker which would to sent to TOrc.
        kubernetes_client: Kubernetes client.
    """

    def __init__(
        self,
        id: str,
        outputs: list[TesOutput] | None,
    ) -> None:
        """Initialize the TOF execution class.

        Args:
            id: The id of the TES task.
            outputs: The list of outputs that Tof will create and monitor.

        Attributes:
            id: The id of the TES task.
            outputs: The list of outputs that TOF will create and monitor.
            message_broker: Message broker client.
            message: Message for the message broker which would to sent to TOrc.
            kubernetes_client: Kubernetes client.
        """
        super().__init__()
        self._task_id = id
        self.outputs = outputs

    @property
    def id(self) -> str:
        """Return the task ID."""
        if self._task_id is None:
            raise ValueError("Task ID is None")
        return self._task_id

    async def start_job(self) -> None:
        """Create the K8s job for Tof."""
        tof_job_name = f"{core_constants.K8s.TOF_PREFIX}-{self.id}"
        metadata = V1ObjectMeta(
            name=tof_job_name,
            labels=get_labels(
                component=core_constants.K8s.TOF_PREFIX,
                task_id=self.id,
                name=tof_job_name,
                parent=f"{core_constants.K8s.TORC_PREFIX}-{self.id}",
            ),
        )
        commands: list[str] = ["poiesis", "tof", "run"]
        await self.create_job(self.id, tof_job_name, commands, metadata)
