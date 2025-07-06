"""Task orchestrator (Torc)."""

import asyncio
import logging

from kubernetes.client import (
    V1ObjectMeta,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1ResourceRequirements,
)

from poiesis.api.tes.models import (
    TesInput,
    TesOutput,
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
        if task.id is None:
            raise ValueError("Task ID is required")
        self.id = task.id
        self.kubernetes_client = KubernetesAdapter()
        self.db = MongoDBClient()
        self.pvc_name = ""
        logger.info(f"Torc initialized with task ID: {self.id}")

    async def execute(self) -> None:
        """Defines the template method, for each service namely Texam, Tif, Tof."""
        assert self.id is not None, "The API should have validated the task name."
        disk_gb = None
        if self.task.resources is not None:
            disk_gb = self.task.resources.disk_gb
            logger.debug(f"Task {self.id} requested disk size: {disk_gb}GB")

        max_retries = 3  # TODO: Make this configurable
        base_delay = 1  # TODO: Make this configurable
        logger.info(
            f"Starting execution of task {self.id} with max_retries={max_retries}"
        )

        assert self.id is not None  # Already checked in execute()

        for attempt in range(max_retries):
            try:
                logger.info(f"Task {self.id}: Attempt {attempt + 1}/{max_retries}")
                # Create PVC
                logger.info(f"Task {self.id}: Creating PVC")
                await self.create_pvc(self.id, disk_gb)

                # Update task state
                logger.info(f"Task {self.id}: Updating task state to RUNNING")
                await self.db.update_task_state(self.id, TesState.RUNNING)
                await self.db.add_task_log(self.id)

                # Execute pipeline stages
                logger.info(f"Task {self.id}: Starting TIF execution")
                await self.tif_execution(self.id, self.task.inputs)

                logger.info(f"Task {self.id}: Starting TExAM execution")
                await self.texam_execution(self.task)

                logger.info(f"Task {self.id}: Starting TOF execution")
                await self.tof_execution(self.id, self.task.outputs, self.task.volumes)

                logger.info(f"Task {self.id}: Adding system logs")
                await self.db.add_tes_task_system_logs(self.id)
                await self.db.add_tes_task_log_end_time(self.id)

                # If we get here, everything succeeded
                logger.info(f"Task {self.id}: Execution completed successfully")
                await self.db.update_task_state(self.id, TesState.COMPLETE)

                # Clean up PVC after successful completion
                await self.kubernetes_client.delete_pvc(self.pvc_name)
                logger.info(f"Task {self.id}: PVC {self.pvc_name} deleted successfully")

                break
            except Exception as e:
                logger.error(
                    f"Task {self.id}: Execution failed on attempt {attempt + 1}: "
                    f"{str(e)}"
                )
                await self.db.add_tes_task_system_logs(self.id)
                await self.db.add_tes_task_log_end_time(self.id)
                await self.kubernetes_client.delete_pvc(self.pvc_name)
                if attempt == max_retries - 1:
                    # On final attempt, let the error propagate
                    logger.error(
                        f"Task {self.id}: All {max_retries} attempts failed, giving up"
                    )
                    raise
                # Otherwise backoff and retry
                delay = base_delay * (2**attempt)  # exponential backoff
                logger.info(f"Task {self.id}: Retrying in {delay} seconds")
                await asyncio.sleep(delay)

    async def create_pvc(self, name: str, size: float | None) -> None:
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
        logger.debug(
            f"PVC storage size: {size}Gi if size else "
            f"{core_constants.K8s.PVC_DEFAULT_DISK_SIZE}"
        )

        if (
            not core_constants.K8s.PVC_ACCESS_MODE
            and not core_constants.K8s.PVC_STORAGE_CLASS
        ):
            logger.warning(
                "PVC access mode and storage class are not set. Using default values."
            )
            logger.debug(f"PVC access mode: {core_constants.K8s.PVC_ACCESS_MODE}")
            logger.debug(f"PVC storage class: {core_constants.K8s.PVC_STORAGE_CLASS}")

        pvc = V1PersistentVolumeClaim(
            api_version="v1",
            kind="PersistentVolumeClaim",
            metadata=V1ObjectMeta(
                name=pvc_name,
                labels={
                    "service": core_constants.K8s.PVC_PREFIX,
                    "name": pvc_name,
                    "parent": core_constants.K8s.TORC_PREFIX,
                },
            ),
            spec=V1PersistentVolumeClaimSpec(
                access_modes=[core_constants.K8s.PVC_ACCESS_MODE]
                if core_constants.K8s.PVC_ACCESS_MODE
                else None,
                storage_class_name=core_constants.K8s.PVC_STORAGE_CLASS or None,
                resources=V1ResourceRequirements(
                    requests={
                        "storage": f"{size}Gi"
                        if size
                        else core_constants.K8s.PVC_DEFAULT_DISK_SIZE
                    }
                ),
            ),
        )
        try:
            self.pvc_name = await self.kubernetes_client.create_pvc(pvc)
            logger.info(f"PVC created: {self.pvc_name}")
        except Exception as e:
            logger.error(f"Failed to create PVC: {str(e)}")
            _id = str(self.id)  # This will be str as we are using uuid4
            logger.error(f"Updating task {_id} state to SYSTEM_ERROR")
            await self.db.update_task_state(_id, TesState.SYSTEM_ERROR)
            raise

    async def tif_execution(self, name: str, inputs: list[TesInput] | None) -> None:
        """Execute the Tif job.

        Args:
            name: Name of the task, will be modified to create Tif job name.
            inputs: List of inputs given in the task.
            volumes: List of volumes given in the task.

        Raises:
            Exception: If the Tif job fails.
        """
        logger.info(f"Starting TIF execution for task {name}")
        if inputs:
            logger.debug(f"Task {name} has {len(inputs)} inputs")
        else:
            logger.debug(f"Task {name} has no inputs")

        if inputs is None or len(inputs) == 0:
            logger.info(f"Task {name} has no inputs, skipping TIF execution")
            return

        try:
            tif_executor = TorcTifExecution(name, inputs)
            await tif_executor.execute()
            logger.info(f"TIF execution completed successfully for task {name}")
        except Exception as e:
            logger.error(f"Failed to execute Tif: {str(e)}")
            _id = str(self.id)  # This will be str as we are using uuid4
            logger.error(f"Updating task {_id} state to SYSTEM_ERROR")
            await self.db.update_task_state(_id, TesState.SYSTEM_ERROR)
            raise

    async def texam_execution(
        self,
        task: TesTask,
    ) -> None:
        """Execute the Texam job.

        Args:
            task: The TES task that needs to be executed.

        Raises:
            Exception: If the Texam job fails.
        """
        logger.info(f"Starting TEXAM execution for task {task.id}")
        try:
            texam_executor = TorcTexamExecution(task)
            await texam_executor.execute()
            logger.info(f"TEXAM execution completed successfully for task {task.id}")
        except Exception as e:
            logger.error(f"Failed to execute Texam: {str(e)}")
            logger.error(e)
            _id = str(self.id)  # This will be str as we are using uuid4
            logger.error(f"Updating task {_id} state to SYSTEM_ERROR")
            await self.db.update_task_state(_id, TesState.SYSTEM_ERROR)
            raise

    async def tof_execution(
        self,
        name: str,
        outputs: list[TesOutput] | None,
        volumes: list[str] | None,
    ) -> None:
        """Execute the Tof job.

        Args:
            name: Name of the task, will be modified to create Tof job name.
            outputs: List of outputs given in the task.
            volumes: List of volumes given in the task.

        Raises:
            Exception: If the Tof job fails.
        """
        logger.info(f"Starting TOF execution for task {name}")

        if outputs:
            logger.debug(f"Task {name} has {len(outputs)} outputs")
        else:
            logger.debug(f"Task {name} has no outputs")

        if outputs is None or len(outputs) == 0:
            logger.info(f"Task {name} has no outputs, skipping TOF execution")
            return

        try:
            tof_executor = TorcTofExecution(name, outputs, volumes)
            await tof_executor.execute()
            logger.info(f"TOF execution completed successfully for task {name}")
        except Exception as e:
            logger.error(f"Failed to execute Tof: {str(e)}")
            _id = str(self.id)  # This will be str as we are using uuid4
            logger.error(f"Updating task {_id} state to SYSTEM_ERROR")
            await self.db.update_task_state(_id, TesState.SYSTEM_ERROR)
            raise
