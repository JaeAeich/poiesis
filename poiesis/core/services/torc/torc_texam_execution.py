"""Create Texam Job and monitor it."""

import json
import logging
from typing import Optional

from kubernetes.client import (
    V1Container,
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
)
from kubernetes.client.exceptions import ApiException

from poiesis.api.tes.models import TesExecutor, TesResources
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.torc.torc_execution_template import TorcExecutionTemplate

core_constants = get_poiesis_core_constants()
logger = logging.getLogger(__name__)


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
        kubernetes_client: Kubernetes
        message_broker: Message broker.
        message: Message for the message broker.
    """

    def __init__(
        self,
        name: str,
        executors: list[TesExecutor],
        resources: Optional[TesResources],
        volumes: Optional[list[str]],
    ) -> None:
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
            kubernetes_client: Kubernetes
            message_broker: Message broker.
            message: Message for the message broker.
        """
        super().__init__()
        self.name = name
        self.executors = executors
        self.resources = resources
        self.volumes = volumes

    async def start_job(self) -> None:
        """Create the K8s job for Texam."""
        texam_name = f"{core_constants.K8s.TEXAM_PREFIX}-{self.name}"
        executors = json.dumps(
            [executor.model_dump_json() for executor in self.executors]
        )
        resources = (
            json.dumps(self.resources.model_dump_json()) if self.resources else "{}"
        )
        volumes = json.dumps(self.volumes) if self.volumes else "[]"
        job = V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=V1ObjectMeta(
                name=texam_name,
                labels={
                    "service": core_constants.K8s.TEXAM_PREFIX,
                    "parent": f"{core_constants.K8s.TORC_PREFIX}-{self.name}",
                    "name": texam_name,
                },
            ),
            spec=V1JobSpec(
                template=V1PodTemplateSpec(
                    spec=V1PodSpec(
                        containers=[
                            V1Container(
                                name=core_constants.K8s.TIF_PREFIX,
                                image=core_constants.K8s.POIESIS_IMAGE,
                                command=["texam"],
                                args=[
                                    "--name",
                                    self.name,
                                    "--executors",
                                    executors,
                                    "--resources",
                                    resources,
                                    "--volumes",
                                    volumes,
                                ],
                            )
                        ],
                        restart_policy="Never",
                    )
                )
            ),
        )
        try:
            await self.kubernetes_client.create_job(job)
        except ApiException as e:
            logger.error(e)
            raise
