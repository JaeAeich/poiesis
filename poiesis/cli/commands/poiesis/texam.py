"""TExAM service CLI commands."""

import asyncio
import json
import sys
from typing import Any

from click import Group, option
from pydantic import ValidationError
from rich.console import Console

from poiesis.api.tes.models import TesTask
from poiesis.cli.commands.poiesis.base import BaseCommand

console = Console()


class TexamCommand(BaseCommand):
    """TExAM CLI command implementation."""

    name = "texam"
    help = "Task Executor and Monitor service"
    description = "Task Executor and Monitor service for managing task execution."

    def add_run_command(self, group: Group):
        """Add TExAM run command.

        Args:
            group: Click group to add the command to
        """

        @group.command(name="run", help="Execute a TExAM task")
        @option("--task", required=True, help="TES task request as JSON")
        def run(task: str):
            """Execute a TExAM task with the provided parameters."""
            from poiesis.core.services.texam.texam import Texam

            try:
                _task = TesTask(**json.loads(task))
            except ValidationError as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)

            console.print(f"[cyan]Executing TExAM task:[/cyan] {_task.id}")
            asyncio.run(Texam(_task).execute())
            console.print("[green]Task execution completed successfully[/green]")

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
