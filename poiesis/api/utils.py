"""Utility functions for the API."""

from functools import wraps
from typing import Any, Callable, TypeVar, cast

from pydantic import BaseModel

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
            return result.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        return result

    return cast(Callable[..., Any], wrapper)
