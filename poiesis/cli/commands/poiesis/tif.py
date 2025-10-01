"""TIF service CLI commands."""

import asyncio
import json
from typing import Any

import click
from pydantic import ValidationError

from poiesis.api.tes.models import TesTask
from poiesis.cli.commands.poiesis.base import BaseCommand
from poiesis.core.constants import get_tes_task_request_path
from poiesis.core.services.filer.filer_strategy_factory import STRATEGY_MAP
from poiesis.core.services.filer.tif import Tif


class TifCommand(BaseCommand):
    """TIF CLI command implementation."""

    name = "tif"
    help = "Task Input Filer service"
    description = "Task Input Filer service for handling task input files."

    def add_run_command(self, group: click.Group) -> None:
        """Add TIF run command.

        Args:
            group: Click group to add the command to
        """

        @group.command(
            name="run",
            help="Execute a TIF task to download input files",
        )
        @click.option("--name", required=True, help="Name of the task")
        def run(name: str):
            """Execute a TIF task with the provided parameters."""
            try:
                with open(get_tes_task_request_path()) as f:
                    task_json: dict[str, Any] = json.load(f)
                tes_task = TesTask(**task_json)
                _inputs = tes_task.inputs or []

                file_count = len(_inputs)
                click.echo("--- TIF Task Information ---")
                click.echo(f"Task: {name}")
                click.echo(f"Input files: {file_count}")
                click.echo("--------------------------")

                click.echo("Downloading input files...")
                asyncio.run(Tif(name, _inputs).execute())

            except json.JSONDecodeError as e:
                raise click.ClickException(f"JSON parsing error: {str(e)}") from e
            except ValidationError as e:
                raise click.ClickException(f"Validation error: {str(e)}") from e
            except Exception as e:
                raise click.ClickException(f"Error: {str(e)}") from e

    def get_info(self) -> dict[str, Any]:
        """Get TIF service information.

        Returns:
            Dictionary with TIF service information
        """
        info = super().get_info()

        info.update(
            {
                "description": "Task Input Filer service for handling task input files",
                "supported_protocols": ", ".join(
                    [
                        v.name if v.input else ""
                        for v in STRATEGY_MAP.values()
                        if v.input
                    ]
                ),
            }
        )

        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
        )
