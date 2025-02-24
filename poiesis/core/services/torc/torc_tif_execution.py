"""Create Tif Job and monitor it."""

import json
import logging
from typing import Optional

from kubernetes.client import (
    V1Container,
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1PersistentVolumeClaimVolumeSource,
    V1PodSpec,
    V1PodTemplateSpec,
    V1Volume,
    V1VolumeMount,
)
from kubernetes.client.exceptions import ApiException

from poiesis.api.tes.models import TesInput
from poiesis.core.constants import PoiesisCoreConstants
from poiesis.core.services.torc.torc_execution_template import TorcExecutionTemplate

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
        tif_job_name = PoiesisCoreConstants.K8s.TIF_PREFIX + self.name
        inputs = (
            json.dumps([input.model_dump_json() for input in self.inputs])
            if self.inputs
            else "[]"
        )

        job = V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=V1ObjectMeta(
                name=tif_job_name,
                labels={
                    "service": PoiesisCoreConstants.K8s.TIF_PREFIX,
                    "name": tif_job_name,
                    "parent": f"{PoiesisCoreConstants.K8s.TORC_PREFIX}-{self.name}",
                },
            ),
            spec=V1JobSpec(
                template=V1PodTemplateSpec(
                    spec=V1PodSpec(
                        containers=[
                            V1Container(
                                name=PoiesisCoreConstants.K8s.TIF_PREFIX,
                                image=PoiesisCoreConstants.K8s.POIESIS_IMAGE,
                                command=["tif"],
                                args=["--name", self.name, "--inputs", inputs],
                                volume_mounts=[
                                    V1VolumeMount(
                                        name=PoiesisCoreConstants.K8s.COMMON_PVC_VOLUME_NAME,
                                        mount_path=PoiesisCoreConstants.K8s.FILER_PVC_PATH,
                                    )
                                ],
                            )
                        ],
                        volumes=[
                            V1Volume(
                                name=PoiesisCoreConstants.K8s.COMMON_PVC_VOLUME_NAME,
                                persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                                    claim_name=f"{PoiesisCoreConstants.K8s.PVC_PREFIX}-{self.name}"
                                ),
                            )
                        ],
                        restart_policy="Never",
                    ),
                )
            ),
        )

        try:
            await self.kubernetes_client.create_job(job)
        except ApiException as e:
            logger.error(e)
            raise
