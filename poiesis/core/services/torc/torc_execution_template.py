"""Torc's template for each service."""

import logging
from abc import ABC, abstractmethod

from kubernetes.client import (
    V1ConfigMapKeySelector,
    V1Container,
    V1EnvVar,
    V1EnvVarSource,
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

from poiesis.core.adaptors.kubernetes.kubernetes import KubernetesAdapter
from poiesis.core.adaptors.message_broker.redis_adaptor import RedisMessageBroker
from poiesis.core.constants import (
    get_configmap_names,
    get_infrastructure_container_security_context,
    get_infrastructure_pod_security_context,
    get_message_broker_envs,
    get_mongo_envs,
    get_poiesis_core_constants,
    get_s3_envs,
    get_secret_names,
)
from poiesis.core.ports.message_broker import Message, MessageStatus
from poiesis.repository.mongo import MongoDBClient

core_constants = get_poiesis_core_constants()

logger = logging.getLogger(__name__)


class TorcExecutionTemplate(ABC):
    """TorcTemplate is a template class for the Torc service.

    Attributes:
        kubernetes_client: Kubernetes client.
        message_broker: Message broker.
        message: Message for the message broker, which would be sent to TOrc.
        db: Database client.
        id: Task identifier
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """Task identifier - must be implemented by subclasses."""
        pass

    def __init__(self) -> None:
        """TorcTemplate initialization.

        Attributes:
            kubernetes_client: Kubernetes client.
            message_broker: Message broker.
            message: Message for the message broker, which would be sent to TOrc.
            db: Database client.
        """
        self.kubernetes_client = KubernetesAdapter()
        self.message_broker = RedisMessageBroker()
        self.message: Message | None = None
        self.db = MongoDBClient()

    async def execute(self) -> None:
        """Defines the template method, for each service namely Texam, Tif, Tof."""
        await self.start_job()
        self.wait()
        await self.log()

    async def create_job(
        self,
        task_id: str,
        job_name: str,
        commands: list[str],
        args: list[str],
        metadata: V1ObjectMeta,
    ) -> None:
        """Create the K8s filer job.

        TIF and TOF jobs are created using this method.

        Args:
            task_id: The id of the task.
            job_name: The name of the job, either TIF or TOF.
            commands: The filer commands to run.
            args: The arguments to pass to the filer commands.
            metadata: The metadata for the job to be used in K8s manifest.
        """
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
            metadata=metadata,
            spec=V1JobSpec(
                backoff_limit=int(core_constants.K8s.BACKOFF_LIMIT),
                template=V1PodTemplateSpec(
                    spec=V1PodSpec(
                        security_context=get_infrastructure_pod_security_context(),
                        containers=[
                            V1Container(
                                name=job_name,
                                image=core_constants.K8s.POIESIS_IMAGE,
                                command=commands,
                                args=args,
                                env=list(get_message_broker_envs())
                                + list(get_mongo_envs())
                                + list(get_s3_envs())
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
                                ],
                                volume_mounts=[
                                    V1VolumeMount(
                                        name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                                        mount_path=core_constants.K8s.FILER_PVC_PATH,
                                    )
                                ],
                                image_pull_policy=core_constants.K8s.IMAGE_PULL_POLICY,
                                security_context=get_infrastructure_container_security_context(),
                            ),
                        ],
                        volumes=[
                            V1Volume(
                                name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                                persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                                    claim_name=f"{core_constants.K8s.PVC_PREFIX}-{task_id}"
                                ),
                            )
                        ],
                        restart_policy=core_constants.K8s.RESTART_POLICY,
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

    @abstractmethod
    async def start_job(self) -> None:
        """Create the K8s job.

        It could be a Tif, Tof or Texam job.
        """
        pass

    def wait(self) -> None:
        """Wait for the job to finish.

        Uses message broker with task name as channel name
        and waits on that channel for the message.
        """
        message = None
        for message in self.message_broker.subscribe(self.id):
            if message:
                if message.status == MessageStatus.ERROR:
                    logger.error(message.message)
                self.message = message
                break

    async def log(self) -> None:
        """Log the job status in TaskDB."""
        if self.message:
            if MessageStatus(self.message.status) == MessageStatus.ERROR:
                logger.error(self.message.message)
                await self.db.add_tes_task_system_logs(self.id, [self.message.message])
                await self.db.add_tes_task_log_end_time(self.id)
                raise RuntimeError(
                    "Exiting due to error condition in asynchronous function."
                )
            else:
                logger.info(self.message.message)
