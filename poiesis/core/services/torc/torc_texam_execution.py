"""Create Texam Job and monitor it."""

import json
import logging

from kubernetes.client import (
    V1ConfigMapKeySelector,
    V1Container,
    V1EnvVar,
    V1EnvVarSource,
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
)
from kubernetes.client.exceptions import ApiException

from poiesis.api.tes.models import TesTask
from poiesis.core.constants import (
    get_configmap_names,
    get_message_broker_envs,
    get_mongo_envs,
    get_poiesis_core_constants,
    get_secret_names,
)
from poiesis.core.services.torc.torc_execution_template import TorcExecutionTemplate

core_constants = get_poiesis_core_constants()
logger = logging.getLogger(__name__)


class TorcTexamExecution(TorcExecutionTemplate):
    """Tif execution class.

    This class is responsible for creating the Texam Job and monitoring it.

    Args:
        task: The TES task that needs to be executed.

    Attributes:
        id: The id of the TES task.
        task: The TES task that needs to be executed.
        kubernetes_client: Kubernetes
        message_broker: Message broker.
        message: Message for the message broker.
    """

    def __init__(
        self,
        task: TesTask,
    ) -> None:
        """Initialize the Tif execution class.

        Args:
            task: The TES task that needs to be executed.

        Attributes:
            id: The id of the TES task.
            task: The TES task that needs to be executed.
            kubernetes_client: Kubernetes
            message_broker: Message broker.
            message: Message for the message broker.
        """
        super().__init__()
        self.id = task.id
        self.task = task

    async def start_job(self) -> None:
        """Create the K8s job for Texam."""
        texam_name = f"{core_constants.K8s.TEXAM_PREFIX}-{self.id}"
        task = json.dumps(self.task.model_dump())
        job = V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=V1ObjectMeta(
                name=texam_name,
                labels={
                    "service": core_constants.K8s.TEXAM_PREFIX,
                    "parent": f"{core_constants.K8s.TORC_PREFIX}-{self.id}",
                    "name": texam_name,
                },
            ),
            spec=V1JobSpec(
                template=V1PodTemplateSpec(
                    spec=V1PodSpec(
                        service_account_name=core_constants.K8s.SERVICE_ACCOUNT_NAME,
                        containers=[
                            V1Container(
                                name=core_constants.K8s.TIF_PREFIX,
                                image=core_constants.K8s.POIESIS_IMAGE,
                                command=["poiesis", "texam", "run"],
                                args=[
                                    "--task",
                                    task,
                                ],
                                image_pull_policy="IfNotPresent",
                                env=list(get_mongo_envs())
                                + list(get_message_broker_envs())
                                + list(get_secret_names())
                                + list(get_configmap_names())
                                + [
                                    V1EnvVar(
                                        name="POIESIS_IMAGE",
                                        value=core_constants.K8s.POIESIS_IMAGE,
                                    ),
                                    V1EnvVar(
                                        name="LOG_LEVEL",
                                        value_from=V1EnvVarSource(
                                            config_map_key_ref=V1ConfigMapKeySelector(
                                                name=core_constants.K8s.CONFIGMAP_NAME,
                                                key="LOG_LEVEL",
                                            )
                                        ),
                                    ),
                                    V1EnvVar(
                                        name="MONITOR_TIMEOUT_SECONDS",
                                        value_from=V1EnvVarSource(
                                            config_map_key_ref=V1ConfigMapKeySelector(
                                                name=core_constants.K8s.CONFIGMAP_NAME,
                                                key="MONITOR_TIMEOUT_SECONDS",
                                                optional=True,
                                            )
                                        ),
                                    ),
                                    V1EnvVar(
                                        name="POIESIS_K8S_NAMESPACE",
                                        value_from=V1EnvVarSource(
                                            config_map_key_ref=V1ConfigMapKeySelector(
                                                name=core_constants.K8s.CONFIGMAP_NAME,
                                                key="POIESIS_K8S_NAMESPACE",
                                            )
                                        ),
                                    ),
                                    V1EnvVar(
                                        name="POIESIS_SERVICE_ACCOUNT_NAME",
                                        value_from=V1EnvVarSource(
                                            config_map_key_ref=V1ConfigMapKeySelector(
                                                name=core_constants.K8s.CONFIGMAP_NAME,
                                                key="POIESIS_SERVICE_ACCOUNT_NAME",
                                            )
                                        ),
                                    ),
                                ],
                            )
                        ],
                        restart_policy="Never",  # TODO: Remove this
                    )
                )
            ),
        )
        logger.debug(job)
        try:
            await self.kubernetes_client.create_job(job)
        except ApiException as e:
            logger.error(e)
            raise
