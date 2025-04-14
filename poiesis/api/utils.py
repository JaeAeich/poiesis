"""Utility functions for the API."""

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from poiesis.api.tes.models import TesTask

T = TypeVar("T")


def pydantic_to_dict_response(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that converts a Pydantic model return value to a dict.

    This decorator is useful for API endpoints that return Pydantic models,
    automatically converting the model to a dictionary using the model_dump method.

    Args:
        func: The function to decorate.

    Returns:
        A wrapped function that converts Pydantic model returns to dictionaries.

    Example:
        ```python
        from pydantic import BaseModel


        class User(BaseModel):
            name: str
            age: int


        @pydantic_to_dict_response
        def get_user() -> User:
            return User(name="John", age=30)


        # When called, get_user() will return a dict: {"name": "John", "age": 30}
        ```
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = await func(*args, **kwargs)
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json", exclude_none=True)
        return result

    return cast(Callable[..., Any], wrapper)


def task_to_minimal_task(task: TesTask) -> TesTask:
    """Convert a task to a minimal task.

    Note: The TES specification says that the task should only return the id, state.
        However, the openAPI spec has the executors as required fields, so we need to
        return a minimal task.
    """
    return TesTask(
        id=task.id,
        state=task.state,
        executors=task.executors,
    )


def task_to_basic_task(task: TesTask) -> TesTask:
    """Convert a task to a basic task.

    Task message will include all fields EXCEPT:
        - tesTask.ExecutorLog.stdout
        - tesTask.ExecutorLog.stderr
        - tesInput.content
        - tesTaskLog.system_logs
    """
    if task.logs:
        for log in task.logs:
            if log.logs:
                for logs in log.logs:
                    logs.stdout = None
                    logs.stderr = None
            log.system_logs = None
    if task.inputs:
        for input in task.inputs:
            input.content = None

    return task
