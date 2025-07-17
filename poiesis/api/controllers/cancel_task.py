"""Controller for canceling tasks."""

import asyncio
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

    async def _clean_task_resources_and_set_final_state(self) -> None:
        """Clean up the task resources and set final state."""
        await self._clean_task_task_resources()
        await self.db.update_task_state(self.task_id, TesState.CANCELED)
        logger.info(f"Task {self.task_id} has been canceled and resources cleaned up.")

    async def _clean_task_task_resources(self) -> None:
        """Clean up the task resources."""
        label_selector = f"tes-task-id={self.task_id}"
        logger.debug(f"Deleting all the jobs with label selector: {label_selector}")

        resources = [
            {
                "name": "jobs",
                "list_fn": self.kubernetes_client.list_jobs_by_label,
                "delete_fn": self.kubernetes_client.delete_jobs_by_label,
                "log_fail": "Failed to delete all jobs after retries and waiting.",
            },
            {
                "name": "pods",
                "list_fn": self.kubernetes_client.list_pods_by_label,
                "delete_fn": self.kubernetes_client.delete_pods_by_label,
                "log_fail": "Failed to delete all pods after retries and waiting.",
            },
            {
                "name": "PVCs",
                "list_fn": self.kubernetes_client.list_pvcs_by_label,
                "delete_fn": self.kubernetes_client.delete_pvcs_by_label,
                "log_fail": "Failed to delete all PVCs after retries and waiting.",
            },
        ]

        max_retries = 3
        for resource in resources:
            logger.debug(
                f"Deleting all the {resource['name']} with "
                f"label selector: {label_selector}"
            )
            try_count = 0
            try:
                list_fn = resource["list_fn"]
                delete_fn = resource["delete_fn"]
                # We can safely cast here as we know the types in the resources list
                while (
                    await list_fn(label_selector)  # type: ignore
                    and try_count <= max_retries
                ):
                    await delete_fn(label_selector)  # type: ignore
                    try_count += 1
                    await asyncio.sleep(2 << try_count)
                if await list_fn(label_selector):  # type: ignore
                    log_fail = resource["log_fail"]

                    logger.warning(log_fail)
            except ApiException as e:
                logger.warning(
                    f"Error deleting {resource['name']} for task {self.task_id}: {e}"
                )
            except TypeError as e:
                logger.error(f"Error calling function: {e}")

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

        if task.state in (
            TesState.COMPLETE,
            TesState.CANCELED,
            TesState.CANCELING,
        ):
            raise BadRequestException(
                f"Task {self.task_id} is already in a terminal state"
                f": {task.state.value}"
            )

        await self.db.update_task_state(self.task_id, TesState.CANCELING)

        asyncio.create_task(self._clean_task_resources_and_set_final_state())

        return TesCancelTaskResponse()
