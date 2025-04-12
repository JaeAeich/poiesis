"""MongoDB adaptor for NoSQL database operations."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import motor.motor_asyncio
from bson.objectid import ObjectId

from poiesis.api.exceptions import DBException
from poiesis.api.tes.models import TesExecutorLog, TesState, TesTask, TesTaskLog
from poiesis.constants import get_poiesis_constants
from poiesis.core.adaptors.kubernetes.kubernetes import KubernetesAdapter
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.models import PodPhase
from poiesis.repository.schemas import TaskSchema

logger = logging.getLogger(__name__)

poiesis_constants = get_poiesis_constants()
poiesis_core_constants = get_poiesis_core_constants()


class MongoDBClient:
    """Simple MongoDB client using Motor for async operations."""

    def __init__(self) -> None:
        """Initialize MongoDB client with connection pooling.

        Args:
            connection_string: MongoDB connection URI
            database: Default database name
            max_pool_size: Maximum number of connections in the pool
        """
        self.connection_string = os.environ.get("MONGODB_CONNECTION_STRING")
        if not self.connection_string:
            logger.error("Environment variable MONGODB_CONNECTION_STRING is not set")
            raise DBException(
                "Environment variable MONGODB_CONNECTION_STRING is not set"
            )
        self.database = poiesis_constants.Database.MongoDB.DATABASE
        self.max_pool_size = poiesis_constants.Database.MongoDB.MAX_POOL_SIZE
        self.client: motor.motor_asyncio.AsyncIOMotorClient = (
            motor.motor_asyncio.AsyncIOMotorClient(
                self.connection_string, maxPoolSize=self.max_pool_size
            )
        )
        self.db = self.client[self.database]
        self.kubernetes_client = KubernetesAdapter()

    async def get_task(self, task_id: str) -> TaskSchema:
        """Get a task from the database.

        Args:
            task_id: ID of the task
        """
        task = await self.db[
            poiesis_constants.Database.MongoDB.TASK_COLLECTION
        ].find_one({"task_id": task_id})
        if task is None:
            raise DBException(f"Task with ID {task_id} not found")
        return TaskSchema(**task)

    async def insert_task(self, task: TaskSchema) -> str:
        """Insert a single document into the specified collection.

        Args:
            task: Task to insert

        Returns:
            The inserted document ID as a string

        Raises:
            DBException: If the document is not valid or the insert operation fails
        """
        try:
            result = await self.db[
                poiesis_constants.Database.MongoDB.TASK_COLLECTION
            ].insert_one(task.model_dump())
            return str(result.inserted_id)
        except Exception as e:
            logger.error(
                "Error inserting document into collection "
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {str(e)}"
            )
            raise DBException(
                "Error inserting document into collection "
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {e}",
            ) from e

    async def update_task_state(self, task_id: str, state: TesState) -> None:
        """Update the state of a task in the database.

        This would be called by jobs in case of task state change or failure.

        Args:
            task_id: ID of the task
            state: State of the task

        Raises:
            DBException: If the update operation fails
        """
        try:
            task = await self.get_task(task_id)
            if task.data.state != state:
                task.data.state = state
                await self.db[
                    poiesis_constants.Database.MongoDB.TASK_COLLECTION
                ].update_one(
                    {"task_id": task_id},
                    {
                        "$set": {
                            "state": state.value,
                            "updated_at": datetime.now(timezone.utc),
                            "data.state": state.value,
                        }
                    },
                )
        except Exception as e:
            logger.error(
                "Error updating document in collection"
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {str(e)}"
            )
            raise DBException(
                "Error updating document in collection"
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {e}",
            ) from e

    async def add_task_log(self, task_id: str) -> None:
        """Add a log for a task in the database.

        Args:
            task_id: ID of the task

        Note:
            This is because the spec defines that in case of task failure and retry,
            another log will be added to the task.
        """
        _log = TesTaskLog(logs=[], outputs=[])
        try:
            task = await self.get_task(task_id)
            task.data.logs = task.data.logs or []
            task.data.logs.append(_log)
            await self.db[
                poiesis_constants.Database.MongoDB.TASK_COLLECTION
            ].update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "data.logs": [log.model_dump() for log in task.data.logs],
                    }
                },
            )
        except Exception as e:
            logger.error(
                "Error adding task log in collection"
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {str(e)}"
            )
            raise DBException(
                "Error adding task log in collection"
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {e}",
            ) from e

    async def add_tes_task_log_end_time(self, task_id: str) -> None:
        """Add the end time of a task in the database.

        Args:
            task_id: ID of the task
        """
        try:
            task = await self.get_task(task_id)
            assert task.data.logs is not None
            task.data.logs[-1].end_time = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S%z"
            )
            await self.db[
                poiesis_constants.Database.MongoDB.TASK_COLLECTION
            ].update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        # TODO: check if this can be optimized with
                        #   data.logs[-1].end_time
                        "data.logs": [log.model_dump() for log in task.data.logs],
                    }
                },
            )
        except Exception as e:
            logger.error(
                "Error adding task log in collection"
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {str(e)}"
            )
            raise DBException(
                "Error adding task log in collection"
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {e}",
            ) from e

    async def add_tes_task_system_logs(
        self, task_id: str, system_logs: Optional[list[str]] = None
    ) -> None:
        """Add system logs for a task in the database.

        Args:
            task_id: ID of the task
            system_logs: System logs to add, custom logs apart from the pod logs.
        """
        try:
            task = await self.get_task(task_id)
            assert task.data.logs is not None

            # Define job prefixes to look for
            job_prefixes = [
                f"{poiesis_core_constants.K8s.TEXAM_PREFIX}-{task_id}",
                f"{poiesis_core_constants.K8s.TOF_PREFIX}-{task_id}",
                f"{poiesis_core_constants.K8s.TIF_PREFIX}-{task_id}",
            ]

            system_logs = system_logs or []

            # Collect logs from all related pods
            for prefix in job_prefixes:
                try:
                    pods = await self.kubernetes_client.get_pods(
                        label_selector=f"job-name={prefix}"
                    )
                    for pod in pods:
                        assert pod.metadata is not None
                        assert pod.metadata.name is not None
                        pod_logs = await self.kubernetes_client.get_pod_log(
                            pod.metadata.name
                        )
                        if pod_logs:
                            assert pod.metadata is not None
                            system_logs.append(
                                f"Logs from {pod.metadata.name}: {pod_logs}"
                            )
                except Exception as e:
                    system_logs.append(f"Error getting logs for {prefix}: {str(e)}")

            # Add system logs to the task
            task.data.logs[-1].system_logs = system_logs

            # Update the task in the database
            await self.db[
                poiesis_constants.Database.MongoDB.TASK_COLLECTION
            ].update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "data.logs": [log.model_dump() for log in task.data.logs],
                    }
                },
            )
        except Exception as e:
            logger.error(
                "Error adding system logs in collection "
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {str(e)}"
            )
            raise DBException(
                "Error adding system logs in collection "
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {e}",
            ) from e

    async def add_task_executor_log(self, task_id: str) -> None:
        """Append a log for a task in the database.

        Each executor has a log.

        Args:
            task_id: ID of the task

        Note:
            This assumes that the executors are called sequentially, hence we will just
            append to the last log.
        """
        # XXX: We initialize the log with exit code 0
        _log = TesExecutorLog(exit_code=0)
        try:
            task = await self.get_task(task_id)
            # This shouldn't be needed as add_task_log should have been called
            task.data.logs = task.data.logs or []
            # Last logs is the current task log, hence we pick the last one
            task.data.logs[-1].logs.append(_log)
            await self.db[
                poiesis_constants.Database.MongoDB.TASK_COLLECTION
            ].update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "data.logs": [log.model_dump() for log in task.data.logs],
                    }
                },
            )
        except Exception as e:
            logger.error(
                "Error upserting task log in collection"
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {str(e)}"
            )
            raise DBException(
                "Error upserting task log in collection"
                f"{poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {e}",
            ) from e

    async def update_executor_log(
        self,
        pod_name: str,
        pod_phase: str,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
    ) -> None:
        """Update the executor log in the database.

        Get the index of the executor from executor name and then updates the idx log
        of executor of the last log of the task.

        Note: If the pods fails to start, we can't call the get_pod_log method. If the
            stdout and stderr are provided, we use them instead of the pod log, else
            try to call the get_pod_log method, if that fails, we use empty strings.

        Args:
            pod_name: Name of the pod
            pod_phase: Phase of the pod
            stdout: Standard output of the pod
            stderr: Standard error of the pod
        """
        try:
            # Note: The executor name is of the form <te_prefix>-<UUID>-<idx>.
            pod_name_without_prefix = pod_name.split(
                f"{poiesis_core_constants.K8s.TE_PREFIX}-"
            )[-1]
            parts = pod_name_without_prefix.split("-")
            idx = int(parts[-1])

            # UUID has 6 parts, hence we take the first 5
            task_id = "-".join(parts[:5])

            task = await self.get_task(task_id)
            assert task.data.logs is not None

            exec_log = task.data.logs[-1].logs[idx]

            exec_log.end_time = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S%z"
            )

            exec_log.stderr = stderr or ""

            try:
                exec_log.stdout = await self.kubernetes_client.get_pod_log(pod_name)
            except Exception as e:
                logger.warning(
                    f"Failed to get pod log for {pod_name} via kubernetes client: {e}"
                )
                exec_log.stdout = stdout or ""

            exec_log.exit_code = 0 if pod_phase == PodPhase.SUCCEEDED.value else 1
            await self.db[
                poiesis_constants.Database.MongoDB.TASK_COLLECTION
            ].update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "data.logs": [log.model_dump() for log in task.data.logs],
                    }
                },
            )
        except Exception as e:
            logger.error(
                "Error updating executor log in collection"
                f" {poiesis_constants.Database.MongoDB.TASK_COLLECTION}: {str(e)}"
            )

    async def list_tasks(
        self,
        query: dict[str, Any],
        page_size: Optional[int] = None,
        next_page_token: Optional[str] = None,
    ) -> tuple[list[TesTask], Optional[str]]:
        """List tasks from the database with pagination.

        Args:
            query: Query to filter tasks
            page_size: Number of tasks to return
            next_page_token: Token for returning the next page of results

        Returns:
            tuple[list[TesTask], Optional[str]]: list of tasks matching the query,
                and next page token
        """
        db_query = query.copy()

        # If there's a next page token, filter documents after that ID
        if next_page_token:
            try:
                db_query["_id"] = {"$gt": ObjectId(next_page_token)}
            except Exception as e:
                raise ValueError("Invalid next_page_token") from e

        cursor = (
            self.db[poiesis_constants.Database.MongoDB.TASK_COLLECTION]
            .find(db_query)
            .sort("_id", 1)
        )

        if page_size is not None:
            cursor = cursor.limit(page_size + 1)

        docs = await cursor.to_list(None)

        tasks = [TesTask(**doc["data"]) for doc in docs[:page_size]]

        next_token = None
        if page_size is not None and len(docs) > page_size:
            next_token = str(docs[page_size]["_id"])

        return tasks, next_token

    @asynccontextmanager
    async def connection(self):
        """Async context manager for explicit connection handling.

        Yields:
            AsyncIOMotorDatabase instance
        """
        try:
            yield self.db
        finally:
            # Motor handles connection pooling internally
            pass

    async def close(self):
        """Close all connections in the pool."""
        self.client.close()
