"""Controller for canceling tasks."""

from typing import Any

from poiesis.api.controllers.interface import InterfaceController
from poiesis.api.exceptions import BadRequestException, NotFoundException
from poiesis.api.tes.models import TesCancelTaskResponse, TesState
from poiesis.core.adaptors.kubernetes.kubernetes import KubernetesAdapter
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.repository.mongo import MongoDBClient

core_constants = get_poiesis_core_constants()


class CancelTaskController(InterfaceController):
    """Controller for canceling a task.

    This controller handles the cancellation of a task in the database.

    Args:
        db: The database client.
        task_id: The ID of the task to cancel.
        user_id: The ID of the user making the request.
    """

    def __init__(
        self,
        db: MongoDBClient,
        task_id: str,
        user_id: str,
    ) -> None:
        """Initialize the controller.

        Args:
            db: The database client.
            task_id: The ID of the task to cancel.
            user_id: The ID of the user making the request.
        """
        self.db = db
        self.task_id = task_id
        self.user_id = user_id
        self.kubernetes_client = KubernetesAdapter()

    async def execute(self, *args: Any, **kwargs: Any) -> TesCancelTaskResponse:
        """Cancel a task.

        Returns:
            A response indicating the task was canceled.

        Raises:
            NotFoundException: If the task is not found for the user.
            BadRequestException: If the task is already completed, canceled, or being
                canceled.
        """
        task = await self.db.get_task(self.task_id)

        if task.user_id != self.user_id:
            raise NotFoundException(f"Task {self.task_id} not found for user")

        if task.state == TesState.COMPLETE:
            raise BadRequestException(f"Task {self.task_id} is already completed")
        elif task.state == TesState.CANCELED:
            raise BadRequestException(f"Task {self.task_id} is already canceled")
        elif task.state == TesState.CANCELING:
            raise BadRequestException(f"Task {self.task_id} is already being canceled")

        jobs = [
            f"{core_constants.K8s.TEXAM_PREFIX}-{self.task_id}",
            f"{core_constants.K8s.TOF_PREFIX}-{self.task_id}",
            f"{core_constants.K8s.TIF_PREFIX}-{self.task_id}",
        ]

        await self.db.update_task_state(self.task_id, TesState.CANCELING)

        pvc_name = f"{core_constants.K8s.TEXAM_PREFIX}-{self.task_id}"
        executor_pod_label_selector = (
            f"parent={core_constants.K8s.TEXAM_PREFIX}-{self.task_id}"
        )

        for job in jobs:
            await self.kubernetes_client.delete_job(job)

        await self.kubernetes_client.delete_pod_by_label_selector(
            executor_pod_label_selector
        )

        await self.kubernetes_client.delete_pvc(pvc_name)

        await self.db.update_task_state(self.task_id, TesState.CANCELED)

        return TesCancelTaskResponse()
