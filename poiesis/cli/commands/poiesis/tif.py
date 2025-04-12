"""TIF service CLI commands."""

import asyncio
import json
import sys
from typing import Any

import rich_click as click
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel

from poiesis.api.tes.models import TesInput
from poiesis.cli.commands.poiesis.base import BaseCommand
from poiesis.core.services.filer.filer_strategy_factory import STRATEGY_MAP
from poiesis.core.services.filer.tif import Tif

console = Console()


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
        @click.option("--inputs", required=True, help="List of task inputs as JSON")
        def run(name: str, inputs: str):
            """Execute a TIF task with the provided parameters.

            Downloads input files for the task based on the provided input
            specifications.

            Example:
                Command line usage:
                ```bash
                $ tif --name md5sum --inputs '[{
                    "url": "s3://my-object-store/file1",
                    "path": "/data/file1"
                }]'
                ```

                Multiple inputs:
                ```bash
                $ tif --name image-processor --inputs '[
                    {
                        "url": "s3://my-object-store/file1",
                        "path": "/data/file1"
                    },
                    {
                        "url": "file://local/file2",
                        "path": "/data/file2"
                    }
                ]'
                ```
            """
            try:
                inputs_json = json.loads(inputs)

                _inputs = [TesInput(**input_) for input_ in inputs_json]

                file_count = len(_inputs)
                console.print(
                    Panel(
                        f"Task: [cyan]{name}[/cyan]\n"
                        f"Input files: [cyan]{file_count}[/cyan]",
                        title="TIF Task Information",
                        border_style="blue",
                    )
                )

                console.print("[cyan]Downloading input files...[/cyan]")
                asyncio.run(Tif(name, _inputs).execute())
                console.print("[green]All input files downloaded successfully[/green]")

            except json.JSONDecodeError as e:
                console.print(f"[bold red]JSON parsing error:[/bold red] {str(e)}")
                sys.exit(1)
            except ValidationError as e:
                console.print(f"[bold red]Validation error:[/bold red] {str(e)}")
                sys.exit(1)
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {str(e)}")
                sys.exit(1)

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
