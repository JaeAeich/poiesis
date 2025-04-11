"""Controllers for the API."""

import uuid
from typing import Any, Optional

from connexion import context
from pydantic import AnyUrl, ValidationError

from poiesis.api.controllers.cancel_task import CancelTaskController
from poiesis.api.controllers.create_task import CreateTaskController
from poiesis.api.controllers.get_task import GetTaskController
from poiesis.api.controllers.list_tasks import ListTasksController
from poiesis.api.exceptions import BadRequestException
from poiesis.api.models import TesListTasksFilter, TesView
from poiesis.api.tes.models import (
    Artifact,
    Organization,
    TesCancelTaskResponse,
    TesCreateTaskResponse,
    TesListTasksResponse,
    TesServiceInfo,
    TesServiceType,
    TesState,
    TesTask,
)
from poiesis.api.utils import pydantic_to_dict_response
from poiesis.cli.utils import get_version
from poiesis.constants import PoesisConstants
from poiesis.repository.mongo import MongoDBClient

constants = PoesisConstants()

db = MongoDBClient()


@pydantic_to_dict_response
async def GetServiceInfo() -> TesServiceInfo:
    """Get service information.

    Returns:
        Service information.
    """
    # TODO: Remove Dummy implementation, and implement real service info
    return TesServiceInfo(
        id="poiesis-tes",
        name="Poiesis TES API",
        description="Task Execution Service API implementation",
        type=TesServiceType(
            group="org.ga4gh",
            artifact=Artifact.tes,
            version=get_version(),
        ),
        contactUrl="mailto:jh4official@gmail.com",
        documentationUrl=AnyUrl(url="https://poiesis.readthedocs.io/en/latest/"),
        environment=constants.ENVIRONMENT,
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
            state=TesState(state) if state else None,
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
async def GetTask(id: str, view: Optional[str] = TesView.MINIMAL.value) -> TesTask:
    """Get a task.

    Returns:
        Task.
    """
    user_id = context.context.get("user")
    _id = uuid.UUID(id)
    if id.lower() != str(_id):
        raise BadRequestException(
            message="Invalid task ID",
            details=f"Task ID {id} is not a valid UUID",
        )
    return await GetTaskController(db=db, id=id, user_id=user_id, view=view).execute()


@pydantic_to_dict_response
async def CancelTask(id: str) -> TesCancelTaskResponse:
    """Cancel a task.

    Returns:
        Canceled task.
    """
    user_id = context.context.get("user")
    return await CancelTaskController(db=db, task_id=id, user_id=user_id).execute()
