"""Controllers for the API."""

from pydantic import AnyUrl

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
def ListTasks() -> TesListTasksResponse:
    """List tasks.

    Returns:
        List of tasks.
    """
    # TODO: Remove Dummy implementation, and implement real list tasks
    return TesListTasksResponse(tasks=[])


@pydantic_to_dict_response
def CreateTask() -> TesCreateTaskResponse:
    """Create a task.

    Returns:
        Created task.
    """
    return TesCreateTaskResponse(id="123")


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
