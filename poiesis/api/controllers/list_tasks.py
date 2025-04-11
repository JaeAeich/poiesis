"""Controller for listing tasks."""

import re
from typing import Any, Optional

from poiesis.api.controllers.interface import InterfaceController
from poiesis.api.models import TesListTasksFilter, TesView
from poiesis.api.tes.models import TesListTasksResponse
from poiesis.api.utils import task_to_basic_task, task_to_minimal_task
from poiesis.repository.mongo import MongoDBClient


class ListTasksController(InterfaceController):
    """Controller for listing tasks.

    This controller handles the listing of tasks from the database.

    Args:
        db: The database client.
        page_size: The number of tasks to return per page.
        page_token: Token for pagination.
        user_id: The ID of the user making the request.
        query_filter: The filter for the list tasks.
    """

    def __init__(
        self,
        db: MongoDBClient,
        user_id: str,
        query_filter: TesListTasksFilter,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> None:
        """Initialize the controller.

        Args:
            db: The database client.
            page_size: The number of tasks to return per page.
            page_token: Token for pagination.
            user_id: The ID of the user making the request.
            query_filter: The filter for the list tasks.
        """
        self.db = db
        self.page_size = page_size
        self.page_token = page_token
        self.user_id = user_id
        self.query_filter = query_filter

    def _build_query(self) -> dict[str, Any]:
        """Build the query for the list tasks.

        Returns:
            A query for the list tasks.
        """
        query: dict[str, Any] = {}
        tag_filter: list[dict[str, Any]] = []

        # Name prefix
        if self.query_filter.name_prefix:
            query["name"] = {"$regex": f"^{re.escape(self.query_filter.name_prefix)}"}

        # State
        if self.query_filter.state:
            query["state"] = self.query_filter.state.value

        # Tags
        if self.query_filter.tag_key:
            for key, val in zip(
                self.query_filter.tag_key, self.query_filter.tag_value or []
            ):
                if val == "":
                    tag_filter.append({f"tags.{key}": {"$exists": True}})
                else:
                    tag_filter.append({f"tags.{key}": val})

        if tag_filter:
            query["$and"] = tag_filter

        if self.user_id:
            query["user_id"] = self.user_id

        return query

    async def execute(self) -> TesListTasksResponse:
        """Execute the controller to list tasks.

        Returns:
            A response containing the list of tasks and pagination token.
        """
        query = self._build_query()
        tasks, next_page_token = await self.db.list_tasks(
            query, self.page_size, self.page_token
        )

        if self.query_filter.view == TesView.MINIMAL:
            return TesListTasksResponse(
                tasks=[task_to_minimal_task(task) for task in tasks],
                next_page_token=next_page_token,
            )
        elif self.query_filter.view == TesView.BASIC:
            return TesListTasksResponse(
                tasks=[task_to_basic_task(task) for task in tasks],
                next_page_token=next_page_token,
            )
        else:
            return TesListTasksResponse(
                tasks=tasks,
                next_page_token=next_page_token,
            )
