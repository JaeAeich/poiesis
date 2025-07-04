"""TOF service CLI commands."""

import asyncio
import json
from typing import Any

import click
from pydantic import ValidationError

from poiesis.api.tes.models import TesOutput
from poiesis.cli.commands.poiesis.base import BaseCommand
from poiesis.core.services.filer.filer_strategy_factory import STRATEGY_MAP
from poiesis.core.services.filer.tof import Tof


class TofCommand(BaseCommand):
    """TOF CLI command implementation."""

    name = "tof"
    help = "Task Output Filer service"
    description = "Task Output Filer service for handling task output files."

    def add_run_command(self, group: click.Group) -> None:
        """Add TOF run command.

        Args:
            group: Click group to add the command to
        """

        @group.command(name="run", help="Execute a TOF task")
        @click.option("--name", required=True, help="Name of the task")
        @click.option("--outputs", required=True, help="List of task outputs as JSON")
        def run(name: str, outputs: str):
            """Execute a TOF task with the provided parameters."""
            try:
                outputs_json = json.loads(outputs)
                _outputs = [TesOutput(**output) for output in outputs_json]

                file_count = len(_outputs)
                click.echo("--- TOF Task Information ---")
                click.echo(f"Task: {name}")
                click.echo(f"Output files: {file_count}")
                click.echo("--------------------------")

                click.echo("Uploading output files...")
                asyncio.run(Tof(name, _outputs).execute())

            except json.JSONDecodeError as e:
                raise click.ClickException(f"JSON parsing error: {str(e)}") from e
            except ValidationError as e:
                raise click.ClickException(f"Validation error: {str(e)}") from e
            except Exception as e:
                raise click.ClickException(f"Error: {str(e)}") from e

    def get_info(self) -> dict[str, Any]:
        """Get TOF service information.

        Returns:
            Dictionary with TOF service information
        """
        info = super().get_info()

        info.update(
            {
                "description": "Task Output Filer service for handling task output "
                "files",
                "supported_protocols": ", ".join(
                    [
                        v.name if v.output else ""
                        for v in STRATEGY_MAP.values()
                        if v.output
                    ]
                ),
            }
        )

        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
        )
