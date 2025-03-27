"""Torc service CLI commands."""

import asyncio
import json
import sys
from typing import Any

import rich_click as click
from rich.console import Console
from rich.panel import Panel

from poiesis.api.tes.models import TesTask
from poiesis.cli.base import BaseCommand
from poiesis.core.services.torc.torc import Torc

console = Console()


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
        @click.option("--task", required=True, help="Task JSON string")
        def run(task: str):
            """Execute a Torc task with the provided task JSON.

            Args:
                task: Task JSON string
            """
            try:
                task_json = json.loads(task)

                tes_task = TesTask(**task_json)

                console.print(
                    Panel(
                        f"Task ID: [cyan]{tes_task.id}[/cyan]\n"
                        f"Name: [cyan]{tes_task.name}[/cyan]",
                        title="Executing Torc Task",
                        border_style="blue",
                    )
                )

                asyncio.run(Torc(tes_task).execute())

                console.print("[green]Task execution completed successfully[/green]")

            except json.JSONDecodeError as e:
                console.print(f"[bold red]JSON parsing error:[/bold red] {str(e)}")
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
                "description": "Task Orchestrator service for orchestrating TES tasks",
            }
        )
        return info
