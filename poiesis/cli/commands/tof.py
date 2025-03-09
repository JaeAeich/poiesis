"""TOF service CLI commands."""

import asyncio
import json
import sys
from typing import Any

import rich_click as click
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel

from poiesis.api.tes.models import TesOutput
from poiesis.cli.base import BaseCommand
from poiesis.core.services.filer.filer_strategy_factory import FilerStrategyFactory
from poiesis.core.services.filer.tof import Tof

console = Console()


class TofCommand(BaseCommand):
    """TOF CLI command implementation."""

    name = "tof"
    help = "Task Output Filer service"
    description = "Task Output Filer service for handling task output files."

    def add_run_command(self, group: click.Group) -> None:
        """Add TOF run command.

        Args:
            group: Click group to add the command to

        Example:
            Command line usage:
            ```bash
            $ tof --name md5sum --outputs '[{
                "path": "/data/outfile",
                "url": "s3://my-object-store/outfile-1",
                "type": "FILE"
            }]'
            ```

            Multiple outputs:
            ```bash
            $ tof --name image-processor --outputs '[
                {
                    "path": "/data/outfile1",
                    "url": "s3://my-object-store/outfile-1",
                    "type": "FILE"
                },
                {
                    "path": "/data/outfile2",
                    "url": "file:///data/outfile-2",
                    "type": "FILE"
                }
            ]'
            ```
        """

        @group.command(name="run", help="Execute a TOF task")
        @click.option("--name", required=True, help="Name of the task")
        @click.option("--outputs", required=True, help="List of task outputs as JSON")
        def run(name: str, outputs: str):
            """Execute a TOF task with the provided parameters.

            Uploads output files for the task based on the provided output
            specifications.
            """
            try:
                outputs_json = json.loads(outputs)

                _outputs = [TesOutput(**output) for output in outputs_json]

                file_count = len(_outputs)
                console.print(
                    Panel(
                        f"Task: [cyan]{name}[/cyan]\n"
                        f"Output files: [cyan]{file_count}[/cyan]",
                        title="TOF Task Information",
                        border_style="blue",
                    )
                )

                console.print("[cyan]Uploading output files...[/cyan]")
                asyncio.run(Tof(name, _outputs).execute())
                console.print("[green]All output files uploaded successfully[/green]")

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
        """Get TOF service information.

        Args:
            extra: Whether to include extra information

        Returns:
            Dictionary with TOF service information
        """
        info = super().get_info()

        info.update(
            {
                "description": "Task Output Filer service for handling task output "
                "files",
                "supported_protocols": ", ".join(
                    [v for _, v in enumerate(FilerStrategyFactory.STRATEGY_MAP)]
                ),
            }
        )

        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
        )
