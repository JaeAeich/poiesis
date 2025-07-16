"""Controller for canceling tasks."""

import logging
from typing import Any

from kubernetes.client.exceptions import ApiException

from poiesis.api.controllers.interface import InterfaceController
from poiesis.api.exceptions import BadRequestException, NotFoundException
from poiesis.api.tes.models import TesCancelTaskResponse, TesState
from poiesis.core.adaptors.kubernetes.kubernetes import KubernetesAdapter
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.repository.mongo import MongoDBClient

core_constants = get_poiesis_core_constants()

logger = logging.getLogger(__name__)


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

        await self.db.update_task_state(self.task_id, TesState.CANCELING)

        label_selector = f"tes-task-id={self.task_id}"
        logger.debug(f"Cancelling all the jobs with label selector: {label_selector}")
        try:
            await self.kubernetes_client.delete_jobs_by_label(label_selector)
        except ApiException as e:
            logger.warning(f"Error deleting jobs for task {self.task_id}: {e}")

        logger.debug(f"Cancelling all the pods with label selector: {label_selector}")
        try:
            await self.kubernetes_client.delete_pods_by_label(label_selector)
        except ApiException as e:
            logger.warning(f"Error deleting pods for task {self.task_id}: {e}")

        logger.debug(f"Cancelling all the PVCs with label selector: {label_selector}")
        try:
            await self.kubernetes_client.delete_pvcs_by_label(label_selector)
        except ApiException as e:
            logger.warning(f"Error deleting PVCs for task {self.task_id}: {e}")

        await self.db.update_task_state(self.task_id, TesState.CANCELED)

        return TesCancelTaskResponse()
