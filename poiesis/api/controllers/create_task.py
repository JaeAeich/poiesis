"""Controller for creating a task."""

import asyncio
import json
import logging
import uuid
from typing import Any

from kubernetes.client.models import (
    V1ConfigMap,
    V1ConfigMapKeySelector,
    V1Container,
    V1EnvVar,
    V1EnvVarSource,
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1OwnerReference,
    V1PodSpec,
    V1PodTemplateSpec,
)

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.controllers.interface import InterfaceController
from poiesis.api.exceptions import DBException
from poiesis.api.tes.models import (
    TesCreateTaskResponse,
    TesState,
    TesTask,
)
from poiesis.constants import get_poiesis_constants
from poiesis.core.adaptors.kubernetes.kubernetes import KubernetesAdapter
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
from poiesis.repository.mongo import MongoDBClient
from poiesis.repository.schemas import TaskSchema

constants = get_poiesis_constants()
api_constants = get_poiesis_api_constants()
core_constants = get_poiesis_core_constants()

logger = logging.getLogger(__name__)


class CreateTaskController(InterfaceController):
    """Controller for creating a task."""

    def __init__(self, db: MongoDBClient, task: TesTask, user_id: str):
        """Initialize the controller.

        Args:
            db: The database client.
            task: The task to create
            user_id: User unique identifier
        """
        self.db = db
        self.task = task
        self.user_id = user_id
        self.kubernetes_client = KubernetesAdapter()

    async def execute(self, *args: Any, **kwargs: Any) -> TesCreateTaskResponse:
        """Execute the controller."""
        _task = self._create_dummy_task_document(self.task)
        try:
            await self.db.insert_task(_task)
        except Exception as e:
            logger.error(f"Failed to create task: {str(e)}")
            raise DBException(
                "Failed to create task",
            ) from e
        asyncio.create_task(self._create_torc_job())
        return TesCreateTaskResponse(id=str(_task.task_id))

    async def _create_tes_task_config_map(self) -> V1ConfigMap:
        task_configmap_name = f"{core_constants.K8s.TES_TASK_PREFIX}-{self.task.id}"
        configmap = V1ConfigMap(
            metadata=V1ObjectMeta(
                name=task_configmap_name,
                namespace=core_constants.K8s.K8S_NAMESPACE,
            ),
            data={
                core_constants.K8s.TES_TASK_CONFIGMAP_KEY: json.dumps(
                    self.task.model_dump()
                )
            },
        )
        _ = await self.kubernetes_client.create_config_map(configmap)
        return configmap

    async def _create_torc_job(self) -> None:
        configmap_to_patch = await self._create_tes_task_config_map()
        torc_job_name = f"{core_constants.K8s.TORC_PREFIX}-{self.task.id}"
        assert self.task.id is not None, "Task ID should already be assigned"
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
                name=torc_job_name,
                namespace=core_constants.K8s.K8S_NAMESPACE,
                labels=get_labels(
                    component=core_constants.K8s.TORC_PREFIX,
                    name=torc_job_name,
                    task_id=str(self.task.id),
                    parent="poiesis-api",
                ),
            ),
            spec=V1JobSpec(
                backoff_limit=int(core_constants.K8s.BACKOFF_LIMIT),
                template=V1PodTemplateSpec(
                    metadata=V1ObjectMeta(
                        labels=get_labels(
                            component=core_constants.K8s.TORC_PREFIX,
                            name=torc_job_name,
                            task_id=str(self.task.id),
                            parent="poiesis-api",
                        ),
                    ),
                    spec=V1PodSpec(
                        service_account_name=core_constants.K8s.SERVICE_ACCOUNT_NAME,
                        security_context=get_infrastructure_pod_security_context(),
                        containers=[
                            V1Container(
                                name=core_constants.K8s.TORC_PREFIX,
                                image=core_constants.K8s.POIESIS_IMAGE,
                                command=["poiesis", "torc", "run"],
                                security_context=get_infrastructure_container_security_context(),
                                env=list(get_message_broker_envs())
                                + list(get_mongo_envs())
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
                                    V1EnvVar(
                                        name="POIESIS_PVC_ACCESS_MODE",
                                        value=core_constants.K8s.PVC_ACCESS_MODE,
                                    ),
                                    V1EnvVar(
                                        name="POIESIS_PVC_STORAGE_CLASS",
                                        value=core_constants.K8s.PVC_STORAGE_CLASS,
                                    ),
                                ],
                                image_pull_policy=core_constants.K8s.IMAGE_PULL_POLICY,
                                volume_mounts=get_infrastructure_security_volume_mount()
                                + get_tes_task_request_volume_mounts(),
                            ),
                        ],
                        restart_policy=core_constants.K8s.RESTART_POLICY,
                        volumes=get_infrastructure_security_volume()
                        + get_tes_task_request_volume(self.task.id),
                    ),
                ),
                ttl_seconds_after_finished=_ttl,
            ),
        )
        logger.debug(job)
        try:
            job: V1Job = await self.kubernetes_client.create_job(job)

            assert job.metadata is not None
            assert job.metadata.name is not None
            assert job.metadata.uid is not None

            owner_ref = V1OwnerReference(
                api_version="batch/v1",
                kind="Job",
                name=job.metadata.name,
                uid=job.metadata.uid,
                controller=True,
                block_owner_deletion=True,
            )

            configmap_to_patch.metadata.owner_references = [owner_ref]

            assert configmap_to_patch.metadata is not None
            assert configmap_to_patch.metadata.name is not None

            await self.kubernetes_client.patch_config_map(
                configmap_to_patch.metadata.name, configmap_to_patch
            )
        except Exception as e:
            logger.error(f"Failed to create TORC job: {str(e)}")
            _id = str(self.task.id)  # This will be str as we are using uuid4
            await self.db.update_task_state(_id, TesState.SYSTEM_ERROR)

    def _create_dummy_task_document(self, task: TesTask) -> TaskSchema:
        _task_id = uuid.uuid4()
        task.id = str(_task_id)
        task.name = task.name or api_constants.Task.NAME
        task.tags = task.tags or {}
        task.state = TesState.INITIALIZING
        return TaskSchema(
            name=task.name,
            state=TesState.INITIALIZING,
            tags=task.tags,
            task_id=str(_task_id),
            user_id=self.user_id,
            service_hash="-1",  # TODO: Add service hash when service is implemented
            data=task,
        )
