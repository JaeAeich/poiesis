"""TExAM service CLI commands."""

import asyncio
import json
from typing import Any

import click
from pydantic import ValidationError

from poiesis.api.tes.models import TesTask
from poiesis.cli.commands.poiesis.base import BaseCommand
from poiesis.core.constants import get_tes_task_request_path
from poiesis.core.services.texam.texam import Texam


class TexamCommand(BaseCommand):
    """TExAM CLI command implementation."""

    name = "texam"
    help = "Task Executor and Monitor service"
    description = "Task Executor and Monitor service for managing task execution."

    def add_run_command(self, group: click.Group):
        """Add TExAM run command.

        Args:
            group: Click group to add the command to
        """

        @group.command(name="run", help="Execute a TExAM task")
        def run():
            """Execute a TExAM task with the provided parameters."""
            try:
                with open(get_tes_task_request_path()) as f:
                    task_json: dict[str, Any] = json.load(f)
                _task = TesTask(**task_json)
            except ValidationError as e:
                raise click.ClickException(f"Validation Error: {e}") from e
            except json.JSONDecodeError as e:
                raise click.ClickException(
                    f"Invalid JSON in --task argument: {e}"
                ) from e

            click.echo(f"Executing TExAM task: {_task.id}")
            asyncio.run(Texam(_task).execute())

    def get_info(self) -> dict[str, Any]:
        """Get TExAM service information.

        Returns:
            Dictionary with TExAM service information
        """
        info = super().get_info()
        info.update(
            {
                "description": "Task Executor and Monitor service for managing task "
                "execution",
            }
        )
        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
        )
