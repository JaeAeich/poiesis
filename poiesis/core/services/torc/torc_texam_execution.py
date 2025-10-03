"""Create Texam Job and monitor it."""

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
    get_infrastructure_container_security_context,
    get_infrastructure_pod_security_context,
    get_infrastructure_security_volume,
    get_infrastructure_security_volume_mount,
    get_labels,
    get_message_broker_envs,
    get_mongo_envs,
    get_poiesis_core_constants,
    get_secret_names,
    get_security_context_envs,
    get_tes_task_request_volume,
    get_tes_task_request_volume_mounts,
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
        self.task = task
        self._task_id = task.id

    @property
    def id(self) -> str:
        """Return the task ID."""
        if self._task_id is None:
            raise ValueError("Task ID is None")
        return self._task_id

    async def start_job(self) -> None:
        """Create the K8s job for Texam."""
        texam_name = f"{core_constants.K8s.TEXAM_PREFIX}-{self.id}"
        try:
            _ttl = (
                int(core_constants.K8s.JOB_TTL) if core_constants.K8s.JOB_TTL else None
            )
        except (ValueError, TypeError):
            logger.warning(
                f"Invalid JOB_TTL {core_constants.K8s.JOB_TTL}, falling back to no TTL "
                "(None).",
            )
            _ttl = None
        job = V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=V1ObjectMeta(
                name=texam_name,
                labels=get_labels(
                    component=core_constants.K8s.TEXAM_PREFIX,
                    task_id=self.id,
                    name=texam_name,
                    parent=f"{core_constants.K8s.TORC_PREFIX}-{self.id}",
                ),
            ),
            spec=V1JobSpec(
                template=V1PodTemplateSpec(
                    metadata=V1ObjectMeta(
                        labels=get_labels(
                            component=core_constants.K8s.TEXAM_PREFIX,
                            name=texam_name,
                            task_id=self.id,
                            parent=f"{core_constants.K8s.TORC_PREFIX}-{self.id}",
                        ),
                    ),
                    spec=V1PodSpec(
                        service_account_name=core_constants.K8s.SERVICE_ACCOUNT_NAME,
                        security_context=get_infrastructure_pod_security_context(),
                        containers=[
                            V1Container(
                                name=core_constants.K8s.TIF_PREFIX,
                                image=core_constants.K8s.POIESIS_IMAGE,
                                command=["poiesis", "texam", "run"],
                                image_pull_policy=core_constants.K8s.IMAGE_PULL_POLICY,
                                security_context=get_infrastructure_container_security_context(),
                                env=list(get_mongo_envs())
                                + list(get_message_broker_envs())
                                + list(get_secret_names())
                                + list(get_configmap_names())
                                + list(get_security_context_envs())
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
                                    V1EnvVar(
                                        name="POIESIS_RESTART_POLICY",
                                        value_from=V1EnvVarSource(
                                            config_map_key_ref=V1ConfigMapKeySelector(
                                                name=core_constants.K8s.CONFIGMAP_NAME,
                                                key="POIESIS_RESTART_POLICY",
                                            )
                                        ),
                                    ),
                                    V1EnvVar(
                                        name="POIESIS_IMAGE_PULL_POLICY",
                                        value_from=V1EnvVarSource(
                                            config_map_key_ref=V1ConfigMapKeySelector(
                                                name=core_constants.K8s.CONFIGMAP_NAME,
                                                key="POIESIS_IMAGE_PULL_POLICY",
                                            )
                                        ),
                                    ),
                                    V1EnvVar(
                                        name="POIESIS_JOB_TTL",
                                        value_from=V1EnvVarSource(
                                            config_map_key_ref=V1ConfigMapKeySelector(
                                                name=core_constants.K8s.CONFIGMAP_NAME,
                                                key="POIESIS_JOB_TTL",
                                            )
                                        ),
                                    ),
                                ],
                                volume_mounts=get_infrastructure_security_volume_mount()
                                + get_tes_task_request_volume_mounts(),
                            )
                        ],
                        restart_policy=core_constants.K8s.RESTART_POLICY,
                        volumes=get_infrastructure_security_volume()
                        + get_tes_task_request_volume(self.id),
                    ),
                ),
                ttl_seconds_after_finished=_ttl,
            ),
        )
        logger.debug(job)
        try:
            await self.kubernetes_client.create_job(job)
        except ApiException as e:
            logger.error(e)
            raise
