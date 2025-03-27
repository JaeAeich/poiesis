"""Task orchestrator (Torc)."""

import asyncio
import logging
from typing import Optional

from kubernetes.client import (
    V1ObjectMeta,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1ResourceRequirements,
)

from poiesis.api.tes.models import (
    TesExecutor,
    TesInput,
    TesOutput,
    TesResources,
    TesState,
    TesTask,
)
from poiesis.core.adaptors.kubernetes.kubernetes import KubernetesAdapter
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.torc.torc_texam_execution import TorcTexamExecution
from poiesis.core.services.torc.torc_tif_execution import TorcTifExecution
from poiesis.core.services.torc.torc_tof_execution import TorcTofExecution
from poiesis.repository.mongo import MongoDBClient

logger = logging.getLogger(__name__)

core_constants = get_poiesis_core_constants()


class Torc:
    """Torc service.

    Args:
        task: Task object from task request

    Attributes:
        task: Task object from task request
        kubernetes_client: Kubernetes client
        pvc_name: Name of the PVC created
    """

    def __init__(self, task: TesTask) -> None:
        """Torc service initialization.

        Args:
            task: Task object from task request

        Attributes:
            task: Task object from task request
            kubernetes_client: Kubernetes client
            pvc_name: Name of the PVC created
        """
        self.task = task
        self.kubernetes_client = KubernetesAdapter()
        self.db = MongoDBClient()

    async def execute(self) -> None:
        """Defines the template method, for each service namely Texam, Tif, Tof."""
        assert self.task.id is not None, "The API should have validated the task name."
        disk_gb = None
        if self.task.resources is not None:
            disk_gb = self.task.resources.disk_gb

        max_retries = 3  # TODO: Make this configurable
        base_delay = 1  # TODO: Make this configurable

        assert self.task.id is not None  # Already checked in execute()

        for attempt in range(max_retries):
            try:
                # Create PVC
                await self.create_pvc(self.task.id, disk_gb)

                # Update task state
                await self.db.update_task_state(self.task.id, TesState.RUNNING)
                await self.db.add_task_log(self.task.id)

                # Execute pipeline stages
                await self.tif_execution(self.task.id, self.task.inputs)
                await self.texam_execution(
                    self.task.id,
                    self.task.executors,
                    self.task.resources,
                    self.task.volumes,
                )
                await self.tof_execution(self.task.id, self.task.outputs)

                # If we get here, everything succeeded
                break
            except Exception:
                if attempt == max_retries - 1:
                    # On final attempt, let the error propagate
                    raise
                # Otherwise backoff and retry
                delay = base_delay * (2**attempt)  # exponential backoff
                await asyncio.sleep(delay)

    async def create_pvc(self, name: str, size: Optional[float]) -> None:
        """Create a PVC for the task.

        Tif and Tof will use this PVC to read and write data, and
        executor will the data from the PVC for its use.

        Args:
            name: Name of the PVC
            size: Size of the PVC

        Raises:
            Exception: If the PVC creation fails.
        """
        pvc_name = f"{core_constants.K8s.PVC_PREFIX}-{name}"
        pvc = V1PersistentVolumeClaim(
            api_version="v1",
            kind="PersistentVolumeClaim",
            metadata=V1ObjectMeta(name=pvc_name),
            spec=V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteMany"],
                resources=V1ResourceRequirements(
                    requests={"storage": f"{size}Gi"}
                    if size
                    else {"storage": core_constants.K8s.PVC_DEFAULT_DISK_SIZE}
                ),
            ),
        )
        try:
            self.pvc_name = await self.kubernetes_client.create_pvc(pvc)
            logger.info(f"PVC created: {self.pvc_name}")
        except Exception as e:
            logger.error(f"Failed to create PVC: {e.__dict__}")
            _id = str(self.task.id)  # This will be str as we are using uuid4
            await self.db.update_task_state(_id, TesState.SYSTEM_ERROR)
            raise

    async def tif_execution(self, name: str, inputs: Optional[list[TesInput]]) -> None:
        """Execute the Tif job.

        Args:
            name: Name of the task, will be modified to create Tif job name.
            inputs: List of inputs given in the task.
            volumes: List of volumes given in the task.

        Raises:
            Exception: If the Tif job fails.
        """
        try:
            await TorcTifExecution(name, inputs).execute()
        except Exception as e:
            logger.error(f"Failed to execute Tif: {e.__dict__}")
            _id = str(self.task.id)  # This will be str as we are using uuid4
            await self.db.update_task_state(_id, TesState.SYSTEM_ERROR)
            raise

    async def texam_execution(
        self,
        name: str,
        executors: list[TesExecutor],
        resources: Optional[TesResources],
        volumes: Optional[list[str]],
    ) -> None:
        """Execute the Texam job.

        Args:
            name: Name of the task, will be modified to create Texam job name.
            executors: List of executors given in the task.
            resources: Resources given in the task.
            volumes: List of volumes given in the task.

        Raises:
            Exception: If the Texam job fails.
        """
        try:
            await TorcTexamExecution(name, executors, resources, volumes).execute()
        except Exception as e:
            logger.error(f"Failed to execute Texam: {e.__dict__}")
            _id = str(self.task.id)  # This will be str as we are using uuid4
            await self.db.update_task_state(_id, TesState.SYSTEM_ERROR)
            raise

    async def tof_execution(
        self,
        name: str,
        outputs: Optional[list[TesOutput]],
    ) -> None:
        """Execute the Tof job.

        Args:
            name: Name of the task, will be modified to create Tof job name.
            outputs: List of outputs given in the task.

        Raises:
            Exception: If the Tof job fails.
        """
        try:
            await TorcTofExecution(name, outputs).execute()
        except Exception as e:
            logger.error(f"Failed to execute Tof: {e.__dict__}")
            _id = str(self.task.id)  # This will be str as we are using uuid4
            await self.db.update_task_state(_id, TesState.SYSTEM_ERROR)
            raise
