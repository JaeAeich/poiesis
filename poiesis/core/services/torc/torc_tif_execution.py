"""Create Tif Job and monitor it."""

import json
import logging
from typing import Optional

from kubernetes.client import (
    V1Container,
    V1EnvVar,
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1PersistentVolumeClaimVolumeSource,
    V1PodSpec,
    V1PodTemplateSpec,
    V1SecretVolumeSource,
    V1Volume,
    V1VolumeMount,
)
from kubernetes.client.exceptions import ApiException

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

    def __init__(self, name: str, inputs: Optional[list[TesInput]]) -> None:
        """Initialize the Tif execution class.

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
        super().__init__()
        self.name = name
        self.inputs = inputs

    async def start_job(self) -> None:
        """Create the K8s job for Tif."""
        tif_job_name = core_constants.K8s.TIF_PREFIX + "-" + self.name
        inputs = (
            json.dumps([input.model_dump() for input in self.inputs])
            if self.inputs
            else "[]"
        )

        job = V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=V1ObjectMeta(
                name=tif_job_name,
                labels={
                    "service": core_constants.K8s.TIF_PREFIX,
                    "name": tif_job_name,
                    "parent": f"{core_constants.K8s.TORC_PREFIX}-{self.name}",
                },
            ),
            spec=V1JobSpec(
                backoff_limit=int(core_constants.K8s.BACKOFF_LIMIT),
                template=V1PodTemplateSpec(
                    spec=V1PodSpec(
                        containers=[
                            V1Container(
                                name=core_constants.K8s.TIF_PREFIX,
                                image=core_constants.K8s.POIESIS_IMAGE,
                                command=["poiesis", "tif", "run"],
                                args=["--name", self.name, "--inputs", inputs],
                                env=[
                                    V1EnvVar(
                                        name="MESSAGE_BROKER_HOST",
                                        value=core_constants.MessageBroker.MESSAGE_BROKER_HOST,
                                    ),
                                    V1EnvVar(
                                        name="MESSAGE_BROKER_PORT",
                                        value=core_constants.MessageBroker.MESSAGE_BROKER_PORT,
                                    ),
                                ],
                                volume_mounts=[
                                    V1VolumeMount(
                                        name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                                        mount_path=core_constants.K8s.FILER_PVC_PATH,
                                    ),
                                    V1VolumeMount(
                                        name=core_constants.K8s.S3_VOLUME_NAME,
                                        mount_path=core_constants.K8s.S3_MOUNT_PATH,
                                        read_only=True,
                                    ),
                                ],
                                image_pull_policy="Never",  # TODO: Remove this
                            ),
                        ],
                        volumes=[
                            V1Volume(
                                name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                                persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                                    claim_name=f"{core_constants.K8s.PVC_PREFIX}-{self.name}"
                                ),
                            ),
                            V1Volume(
                                name=core_constants.K8s.S3_VOLUME_NAME,
                                secret=V1SecretVolumeSource(
                                    secret_name=core_constants.K8s.S3_SECRET_NAME
                                ),
                            ),
                        ],
                        restart_policy="Never",
                    ),
                ),
            ),
        )

        try:
            await self.kubernetes_client.create_job(job)
        except ApiException as e:
            logger.error(e)
            raise
