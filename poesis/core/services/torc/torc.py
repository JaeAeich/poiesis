"""Task orchestrator (Torc)."""

from typing import Optional

from poesis.api.tes.models import (
    TesExecutor,
    TesInput,
    TesOutput,
    TesResources,
    TesTask,
)
from poesis.core.services.torc.torc_texam_execution import TorcTexamExecution
from poesis.core.services.torc.torc_tif_execution import TorcTifExecution
from poesis.core.services.torc.torc_tof_execution import TorcTofExecution


class Torc:
    """Torc service.

    Args:
        task: Task object from task request

    Attributes:
        task: Task object from task request
    """

    def __init__(self, task: TesTask) -> None:
        """Torc service initialization.

        Args:
            task: Task object from task request

        Attributes:
            task: Task object from task request
        """
        self.task = task

    async def execute(self) -> None:
        """Defines the template method, for each service namely Texam, Tif, Tof."""
        assert self.task.name is not None, (
            "The API should have validated the task name."
        )
        disk_gb = None
        if self.task.resources is not None:
            disk_gb = self.task.resources.disk_gb
        await self.create_pvc(self.task.name, disk_gb)
        await self.tif_execution(self.task.name, self.task.inputs, self.task.volumes)
        await self.texam_execution(
            self.task.name, self.task.executors, self.task.resources, self.task.volumes
        )
        await self.tof_execution(self.task.name, self.task.outputs, self.task.volumes)

    async def create_pvc(self, name: str, size: Optional[float]) -> None:
        """Create a PVC for the task.

        Args:
            name: Name of the PVC
            size: Size of the PVC
        """
        pass

    async def tif_execution(
        self, name: str, inputs: Optional[list[TesInput]], volumes: Optional[list[str]]
    ) -> None:
        """Execute the Tif job.

        Args:
            name: Name of the task, will be modified to create Tif job name.
            inputs: List of inputs given in the task.
            volumes: List of volumes given in the task.
        """
        TorcTifExecution(name, inputs, volumes).execute()

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
        volumes: Optional[list[str]],
    ) -> None:
        """Execute the Tof job.

        Args:
            name: Name of the task, will be modified to create Tof job name.
            outputs: List of outputs given in the task.
            volumes: List of volumes given in the task.
        """
        TorcTofExecution(name, outputs, volumes).execute()
