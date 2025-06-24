"""Controller for getting a task."""

from typing import Any

from poiesis.api.controllers.interface import InterfaceController
from poiesis.api.exceptions import NotFoundException
from poiesis.api.models import TesView
from poiesis.api.tes.models import TesTask
from poiesis.api.utils import task_to_basic_task
from poiesis.repository.mongo import MongoDBClient


class GetTaskController(InterfaceController):
    """Controller for getting a task.

    This controller handles retrieving a specific task from the database.

    Args:
        db: The database client.
        id: The ID of the task to retrieve.
        user_id: The ID of the user to retrieve the task for.
        view: The view to retrieve the task in.
    """

    def __init__(
        self,
        db: MongoDBClient,
        id: str,
        user_id: str,
        view: str | None = TesView.MINIMAL.value,
    ) -> None:
        """Initialize the controller.

        Args:
            db: The database client.
            id: The ID of the task to retrieve.
            user_id: The ID of the user to retrieve the task for.
            view: The view to retrieve the task in.
        """
        self.db = db
        self.id = id
        self.user_id = user_id
        self.view = TesView(view) if view else TesView.MINIMAL

    async def execute(self, *args: Any, **kwargs: Any) -> TesTask:
        """Execute the controller to get a task.

        Returns:
            The requested task.

        Raises:
            NotFoundException: If the task is not found.
        """
        task = await self.db.get_task(self.id)
        if not task:
            raise NotFoundException(f"Task with ID {self.id} not found")

        if task.user_id != self.user_id:
            raise NotFoundException(f"Task with ID {self.id} not found")

        if self.view == TesView.MINIMAL:
            return TesTask(
                id=str(task.data.id),
                state=task.data.state,
                executors=task.data.executors,
            )
        elif self.view == TesView.BASIC:
            return task_to_basic_task(task.data)
        else:
            return task.data
