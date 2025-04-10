"""Controllers for the API."""

from typing import Any
from typing import Any, Optional

from connexion import context
from pydantic import AnyUrl, ValidationError

from poiesis.api.controllers.create_task import CreateTaskController
from poiesis.api.controllers.list_tasks import ListTasksController
from poiesis.api.exceptions import BadRequestException
from poiesis.api.models import TesListTasksFilter, TesView
from poiesis.api.tes.models import (
    Organization,
    TesCancelTaskResponse,
    TesCreateTaskResponse,
    TesListTasksResponse,
    TesServiceInfo,
    TesTask,
)
from poiesis.api.utils import pydantic_to_dict_response
from poiesis.cli.utils import get_version
from poiesis.repository.mongo import MongoDBClient

db = MongoDBClient()


@pydantic_to_dict_response
def GetServiceInfo() -> TesServiceInfo:
    """Ger service information.

    Returns:
        Service information.
    """
    # TODO: Remove Dummy implementation, and implement real service info
    return TesServiceInfo(
        id="poiesis-tes",
        name="Poiesis TES API",
        description="Task Execution Service API implementation",
        organization=Organization(
            name="Poiesis",
            url=AnyUrl(url="http://www.example.com"),
        ),
        version=get_version(),
    )


@pydantic_to_dict_response
async def ListTasks(  # noqa: PLR0913
    name_prefix: Optional[str] = None,
    state: Optional[str] = TesState.UNKNOWN.value,
    tag_key: Optional[list[str]] = None,
    tag_value: Optional[list[str]] = None,
    page_size: Optional[int] = None,
    page_token: Optional[str] = None,
    view: Optional[str] = TesView.MINIMAL.value,
) -> TesListTasksResponse:
    """List tasks.

    Args:
        name_prefix: Optional prefix for task names.
        state: Optional state for filtering tasks.
        tag_key: Optional tag key for filtering tasks.
        tag_value: Optional tag value for filtering tasks.
        page_size: Optional number of tasks per page.
        page_token: Optional token for pagination.
        view: Optional view for filtering tasks.

    Returns:
        List of tasks.
    """
    try:
        query_filter = TesListTasksFilter(
            name_prefix=name_prefix,
            state=state,
            tag_key=tag_key,
            tag_value=tag_value,
            view=TesView(view),
        )
    except ValidationError as e:
        raise BadRequestException(
            message="Invalid request body",
            details=e.errors(),
        ) from e
    return await ListTasksController(
        db=db,
        user_id=context.context.get("user"),
        query_filter=query_filter,
        page_size=page_size,
        page_token=page_token,
    ).execute()


@pydantic_to_dict_response
async def CreateTask(body: dict[str, Any]) -> TesCreateTaskResponse:
    """Create a task.

    Returns:
        Created task.
    """
    try:
        user_id = context.context.get("user")
        task = TesTask(**body)
    except ValidationError as e:
        raise BadRequestException(
            message="Invalid request body",
            details=e.errors(),
        ) from e
    controller = CreateTaskController(db=db, task=task, user_id=user_id)
    return await controller.execute()


@pydantic_to_dict_response
def GetTask() -> TesTask:
    """Get a task.

    Returns:
        Task.
    """
    # TODO: Remove Dummy implementation, and implement real get task
    return TesTask(id="123", executors=[])


@pydantic_to_dict_response
def CancelTask() -> TesCancelTaskResponse:
    """Cancel a task.

    Returns:
        Canceled task.
    """
    # TODO: Remove Dummy implementation, and implement real cancel task
    return TesCancelTaskResponse()
