"""API service CLI commands."""

import asyncio
import json
from enum import Enum
from typing import Any

import rich_click as click
import yaml
from pydantic import BaseModel, ValidationError
from rich.console import Console

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.controllers.cancel_task import CancelTaskController
from poiesis.api.controllers.create_task import CreateTaskController
from poiesis.api.controllers.get_task import GetTaskController
from poiesis.api.controllers.list_tasks import ListTasksController
from poiesis.api.models import TesListTasksFilter, TesView
from poiesis.api.security import validate_bearer_token
from poiesis.api.tes.models import TesState, TesTask
from poiesis.cli.commands.tes.base import BaseCommand
from poiesis.constants import get_poiesis_constants
from poiesis.repository.mongo import MongoDBClient

api_constants = get_poiesis_api_constants()
constants = get_poiesis_constants()


console = Console()
db = MongoDBClient()


class OutputFormat(Enum):
    """Output format of the command."""

    JSON = "json"
    TEXT = "text"
    YAML = "yaml"


class TaskCommand(BaseCommand):
    """Task CLI command implementation."""

    name = "task"
    help = "Task management"
    description = "Commands to manage tasks."

    def add_create_task_command(self, group: click.Group) -> None:
        """Add create task command.

        Args:
            group: Click group to add the command to
        """

        @group.command(name="create", help="Create a task")
        @click.option("--task", required=True, help="TES task request JSON string")
        @click.option("--token", required=True, help="User auth token")
        @click.option(
            "--format",
            type=click.Choice(
                [
                    OutputFormat.__members__[member].value
                    for member in OutputFormat.__members__
                ]
            ),
            required=False,
            help="Output format",
        )
        def create(task: str, token: str, format: str | None = OutputFormat.YAML.value):
            """Create a task.

            Args:
                task: TES task request JSON string
                token: User auth token
                format: Output format
            """
            try:
                user_id = self._get_user_id(token)
                _format = OutputFormat(format) if format else OutputFormat.YAML

                try:
                    task_json = json.loads(task)
                except json.JSONDecodeError as e:
                    raise click.ClickException(
                        f"Invalid task: not a valid JSON: {e}"
                    ) from e

                _task = TesTask(**task_json)

                controller = CreateTaskController(db=db, task=_task, user_id=user_id)
                response = asyncio.run(controller.execute())
                self._create_output_response(response, _format)

            except ValidationError as e:
                raise click.ClickException(f"Invalid task format: {str(e)}") from e
            except click.ClickException:
                raise
            except Exception as e:
                error_message = getattr(e, "message", str(e))
                raise click.ClickException(f"Operation failed: {error_message}") from e

    def add_get_task_command(self, group: click.Group) -> None:
        """Add the get task command to the group.

        Args:
            group: Click group to add the command to
        """

        @group.command(name="get", help="Get a task by ID")
        @click.option("--id", required=True, help="Task ID")
        @click.option("--token", required=True, help="User auth token")
        @click.option("--view", required=False, help="Task view")
        @click.option(
            "--format",
            type=click.Choice(
                [
                    OutputFormat.__members__[member].value
                    for member in OutputFormat.__members__
                ]
            ),
            required=False,
            help="Output format",
        )
        def get(
            id: str,
            token: str,
            view: str | None = TesView.MINIMAL.value,
            format: str | None = OutputFormat.YAML.value,
        ):
            """Get a task.

            Args:
                id: Task ID
                token: User auth token
                view: Task view
                format: Output format
            """
            try:
                view = TesView(view).value if view else TesView.MINIMAL.value
                _format = OutputFormat(format) if format else OutputFormat.YAML

                user_id = self._get_user_id(token)

                controller = GetTaskController(db=db, id=id, user_id=user_id, view=view)
                response = asyncio.run(controller.execute())

                self._create_output_response(response, _format)
            except Exception as e:
                raise click.ClickException(f"Operation failed: {e}") from e

    def add_cancel_task_command(self, group: click.Group) -> None:
        """Add the cancel task command to the group.

        Args:
            group: Click group to add the command to
        """

        @group.command(name="cancel", help="Cancel a task by ID")
        @click.option("--id", required=True, help="Task ID")
        @click.option("--token", required=True, help="User auth token")
        @click.option(
            "--format",
            type=click.Choice(
                [
                    OutputFormat.__members__[member].value
                    for member in OutputFormat.__members__
                ]
            ),
            required=False,
            help="Output format",
        )
        def cancel(id: str, token: str, format: str | None = OutputFormat.YAML.value):
            """Cancel a task."""
            try:
                user_id = self._get_user_id(token)
                controller = CancelTaskController(db=db, task_id=id, user_id=user_id)
                response = asyncio.run(controller.execute())
                self._create_output_response(response, OutputFormat(format))
            except Exception as e:
                raise click.ClickException(f"Operation failed: {e}") from e

    def add_list_tasks_command(self, group: click.Group) -> None:
        """Add the list tasks command to the group.

        Args:
            group: Click group to add the command to
        """

        @group.command(name="list", help="Get list of tasks")
        @click.option("--token", required=True, help="User auth token")
        @click.option(
            "--name-prefix", type=str, required=False, help="Name prefix of the task"
        )
        @click.option(
            "--state",
            type=click.Choice(
                [TesState.__members__[member].value for member in TesState.__members__]
            ),
            required=False,
            help="State of the task, PENDING, RUNNING, COMPLETED, CANCELLED, FAILED",
        )
        @click.option(
            "--tag-key",
            type=str,
            required=False,
            help="Tag keys as JSON array",
        )
        @click.option(
            "--tag-value",
            type=str,
            required=False,
            help="Tag values as JSON array",
        )
        @click.option(
            "--view",
            type=click.Choice(
                [TesView.__members__[member].value for member in TesView.__members__]
            ),
            required=False,
            help="View of the task, MINIMAL, BASIC or FULL",
        )
        @click.option(
            "--format",
            type=click.Choice(
                [
                    OutputFormat.__members__[member].value
                    for member in OutputFormat.__members__
                ]
            ),
            required=False,
            help="Output format",
        )
        def list(  # noqa: PLR0913
            token: str,
            format: str | None = OutputFormat.YAML.value,
            page_size: int | None = None,
            page_token: str | None = None,
            name_prefix: str | None = None,
            state: str | None = None,
            tag_key: str | None = None,
            tag_value: str | None = None,
            view: str | None = TesView.MINIMAL.value,
        ):
            """List tasks.

            Args:
                token: User auth token
                format: Output format
                page_size: Page size
                page_token: Page token
                name_prefix: Name prefix
                state: State of the task
                tag_key: Tag key
                tag_value: Tag value
                view: View of the task
            """
            try:
                user_id = self._get_user_id(token)
                _view = TesView(view) if view else TesView.MINIMAL
                output_format = OutputFormat(format) if format else OutputFormat.YAML
                _filter = TesListTasksFilter(
                    name_prefix=name_prefix,
                    state=TesState(state) if state else None,
                    tag_key=json.loads(tag_key) if tag_key else None,
                    tag_value=json.loads(tag_value) if tag_value else None,
                    view=_view,
                )
                controller = ListTasksController(
                    db=db,
                    user_id=user_id,
                    page_size=int(page_size) if page_size else None,
                    page_token=page_token,
                    query_filter=_filter,
                )
                response = asyncio.run(controller.execute())
                self._create_output_response(response, output_format)
            except Exception as e:
                raise click.ClickException(f"Operation failed: {e}") from e

    def _get_user_id(self, token: str) -> str:
        """Get the user ID from the token.

        Args:
            token: User auth token
        """
        token_data = validate_bearer_token(token)
        if not token_data or "sub" not in token_data:
            raise click.ClickException("Invalid token: missing user identifier")

        user_id = token_data.get("sub")
        if not user_id or not isinstance(user_id, str):
            raise click.ClickException("Invalid token: missing user identifier")

        return str(user_id)

    def _create_output_response(
        self, response: BaseModel, format: OutputFormat
    ) -> None:
        """Create the output response.

        Args:
            response: Response to create the output for
            format: Output format
        """
        _response: dict[str, Any] = (
            response.model_dump(exclude_none=True, mode="json")
            if isinstance(response, BaseModel)
            else response
        )

        if format == OutputFormat.JSON:
            console.print(json.dumps(_response, indent=4))
        elif format == OutputFormat.YAML:
            console.print(yaml.dump(_response))
        else:
            console.print(_response)
