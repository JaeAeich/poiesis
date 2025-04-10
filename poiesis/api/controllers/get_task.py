"""Controller for getting a task."""

from typing import Optional

from poiesis.api.controllers.interface import InterfaceController
from poiesis.api.exceptions import NotFoundException
from poiesis.api.models import TesView
from poiesis.api.tes.models import TesTask
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
        view: Optional[str] = TesView.MINIMAL.value,
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
        self.view = view

    async def execute(self) -> TesTask:
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

        if self.view == TesView.MINIMAL.value:
            return TesTask(
                id=str(task.data.id),
                state=task.data.state,
                executors=task.data.executors,
            )
        elif self.view == TesView.BASIC.value:
            return task.data
        else:
            return task.data
