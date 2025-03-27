"""Controller for creating a task."""

import asyncio
import logging
import uuid

from poiesis.api.constants import PoiesisApiConstants
from poiesis.api.controllers.interface import InterfaceController
from poiesis.api.exceptions import DBException
from poiesis.api.tes.models import TesCreateTaskResponse, TesTask
from poiesis.constants import get_poiesis_constants
from poiesis.core.services.torc.torc import Torc
from poiesis.repository.mongo import MongoDBClient
from poiesis.repository.schemas import TaskSchema

api_constants = PoiesisApiConstants()
constants = get_poiesis_constants()
logger = logging.getLogger(__name__)


class CreateTaskController(InterfaceController):
    """Controller for creating a task."""

    def __init__(self, db: MongoDBClient, task: TesTask):
        """Initialize the controller.

        Args:
            db: The database client.
            task: The task to create.
        """
        self.db = db
        self.task = task
        self.torc = Torc(task)

    async def execute(self) -> TesCreateTaskResponse:
        """Execute the controller."""
        _task = self._create_dummy_task_document(self.task)
        try:
            await self.db.insert_one(
                collection=constants.Database.MongoDB.TASK_COLLECTION,
                document=_task,
            )
        except Exception as e:
            logger.error(f"Failed to create task: {e.__dict__}")
            raise DBException(
                "Failed to create task",
            ) from e
        # Execute the task in the background without waiting for it to complete
        asyncio.create_task(self.torc.execute())
        # Note: _task.id won't be none as we are using uuid4
        # and it will be a valid uuid, using str() to
        # silence the type checker
        return TesCreateTaskResponse(id=str(_task.id))

    def _create_dummy_task_document(self, task: TesTask) -> TaskSchema:
        _task_id = uuid.uuid4()
        task.id = str(_task_id)
        task.name = task.name or api_constants.Task.NAME
        task.tags = task.tags or {}
        return TaskSchema(
            name=task.name,
            tags=task.tags,
            task_id=str(_task_id),
            user_id="-1",  # TODO: Add user id after authentication is implemented
            service_hash="-1",  # TODO: Add service hash when service is implemented
            data=task,
        )
