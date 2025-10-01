"""Torc service CLI commands."""

import asyncio
import json
from typing import Any

import click
from pydantic import ValidationError

from poiesis.api.tes.models import TesTask
from poiesis.cli.commands.poiesis.base import BaseCommand
from poiesis.core.constants import get_tes_task_request_path
from poiesis.core.services.torc.torc import Torc


class TorcCommand(BaseCommand):
    """Torc CLI command implementation."""

    name = "torc"
    help = "Task Orchestrator service"
    description = "Task Orchestrator service for orchestrating TES tasks."

    def add_run_command(self, group: click.Group) -> None:
        """Add Torc run command.

        Args:
            group: Click group to add the command to
        """

        @group.command(name="run", help="Execute a Torc task")
        def run():
            """Execute a Torc task with the provided task JSON file."""
            try:
                with open(get_tes_task_request_path()) as f:
                    task_json: dict[str, Any] = json.load(f)
                tes_task = TesTask(**task_json)

                click.echo("--- Executing Torc Task ---")
                click.echo(f"Task ID: {tes_task.id}")
                click.echo(f"Name: {tes_task.name}")
                click.echo("---------------------------")

                asyncio.run(Torc(tes_task).execute())

            except json.JSONDecodeError as e:
                raise click.ClickException(f"JSON parsing error: {str(e)}") from e
            except ValidationError as e:
                raise click.ClickException(f"Validation error: {str(e)}") from e
            except Exception as e:
                raise click.ClickException(f"Error: {str(e)}") from e

    def get_info(self) -> dict[str, Any]:
        """Get Torc service information.

        Returns:
            Dictionary with TOF service information
        """
        info = super().get_info()
        info.update(
            {
                "description": "Task Orchestrator service for orchestrating TES tasks",
            }
        )
        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
        )
