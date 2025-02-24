"""Task orchestrator (Torc)."""

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
    TesTask,
)
from poiesis.core.adaptors.kubernetes.kubernetes import KubernetesAdapter
from poiesis.core.constants import PoiesisCoreConstants
from poiesis.core.services.torc.torc_texam_execution import TorcTexamExecution
from poiesis.core.services.torc.torc_tif_execution import TorcTifExecution
from poiesis.core.services.torc.torc_tof_execution import TorcTofExecution

logger = logging.getLogger(__name__)


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

    async def execute(self) -> None:
        """Defines the template method, for each service namely Texam, Tif, Tof."""
        assert self.task.name is not None, (
            "The API should have validated the task name."
        )
        disk_gb = None
        if self.task.resources is not None:
            disk_gb = self.task.resources.disk_gb
        await self.create_pvc(self.task.name, disk_gb)
        await self.tif_execution(self.task.name, self.task.inputs)
        await self.texam_execution(
            self.task.name, self.task.executors, self.task.resources, self.task.volumes
        )
        await self.tof_execution(self.task.name, self.task.outputs)

    async def create_pvc(self, name: str, size: Optional[float]) -> None:
        """Create a PVC for the task.

        Tif and Tof will use this PVC to read and write data, and
        executor will the data from the PVC for its use.

        Args:
            name: Name of the PVC
            size: Size of the PVC
        """
        pvc_name = f"{PoiesisCoreConstants.K8s.PVC_PREFIX}-{name}"
        pvc = V1PersistentVolumeClaim(
            api_version="v1",
            kind="PersistentVolumeClaim",
            metadata=V1ObjectMeta(name=pvc_name),
            spec=V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteMany"],
                resources=V1ResourceRequirements(
                    requests={"storage": f"{size}Gi"}
                    if size
                    else {"storage": PoiesisCoreConstants.K8s.PVC_DEFAULT_DISK_SIZE}
                ),
            ),
        )
        self.pvc_name = await self.kubernetes_client.create_pvc(pvc)
        logger.info(f"PVC created: {self.pvc_name}")

    async def tif_execution(self, name: str, inputs: Optional[list[TesInput]]) -> None:
        """Execute the Tif job.

        Args:
            name: Name of the task, will be modified to create Tif job name.
            inputs: List of inputs given in the task.
            volumes: List of volumes given in the task.
        """
        TorcTifExecution(name, inputs).execute()

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
        """
        TorcTexamExecution(name, executors, resources, volumes).execute()

    async def tof_execution(
        self,
        name: str,
        outputs: Optional[list[TesOutput]],
    ) -> None:
        """Execute the Tof job.

        Args:
            name: Name of the task, will be modified to create Tof job name.
            outputs: List of outputs given in the task.
        """
        TorcTofExecution(name, outputs).execute()
