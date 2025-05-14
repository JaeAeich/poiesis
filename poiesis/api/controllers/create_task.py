"""Controller for creating a task."""

import asyncio
import json
import logging
import uuid

from kubernetes.client.models import (
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
    get_message_broker_envs,
    get_mongo_envs,
    get_poiesis_core_constants,
    get_secret_names,
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

    async def execute(self) -> TesCreateTaskResponse:
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

    async def _create_torc_job(self) -> None:
        torc_job_name = f"{core_constants.K8s.TORC_PREFIX}-{self.task.id}"
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
                labels={
                    "service": core_constants.K8s.TORC_PREFIX,
                    "name": torc_job_name,
                    "parent": "poiesis-api",
                },
            ),
            spec=V1JobSpec(
                backoff_limit=int(core_constants.K8s.BACKOFF_LIMIT),
                template=V1PodTemplateSpec(
                    spec=V1PodSpec(
                        service_account_name=core_constants.K8s.SERVICE_ACCOUNT_NAME,
                        containers=[
                            V1Container(
                                name=core_constants.K8s.TORC_PREFIX,
                                image=core_constants.K8s.POIESIS_IMAGE,
                                command=["poiesis", "torc", "run"],
                                args=["--task", json.dumps(self.task.model_dump())],
                                env=list(get_message_broker_envs())
                                + list(get_mongo_envs())
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
                                image_pull_policy=core_constants.K8s.IMAGE_PULL_POLICY,
                            ),
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
