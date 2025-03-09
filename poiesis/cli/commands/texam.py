"""TExAM service CLI commands."""

import asyncio
import json
import sys
from typing import Any, Optional

from click import Group, option
from pydantic import ValidationError
from rich.console import Console

from poiesis.api.tes.models import TesExecutor, TesResources
from poiesis.cli.base import BaseCommand

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

        Example:
            Command line usage:
            ```bash
            $ texam --name "md5sum-task"
                --executors
                '[{"image":"ubuntu:20.04","command":["/bin/md5sum","/data/file1"]}]'
                --resources '{"cpu_cores":1,"ram_gb":2,"disk_gb":10}'
                --volumes '["/shared-data"]'
            ```

            Complex example:
            ```bash
            $ texam --name "complex-analysis" --executors '[{
                "image": "ubuntu:20.04",
                "command": ["/bin/md5", "/data/file1"],
                "workdir": "/data/",
                "stdin": "/data/file1",
                "stdout": "/tmp/stdout.log",
                "stderr": "/tmp/stderr.log",
                "env": {
                    "BLASTDB": "/data/GRC38",
                    "HMMERDB": "/data/hmmer"
                },
                "ignore_error": true
            }]' --resources '{
                "cpu_cores": 4,
                "preemptible": false,
                "ram_gb": 8,
                "disk_gb": 40,
                "zones": ["us-west-1"],
                "backend_parameters": {
                    "VmSize": "Standard_D64_v3"
                },
                "backend_parameters_strict": false
            }' --volumes '["/vol/A/"]'
            ```
        """

        @group.command(name="run", help="Execute a TExAM task")
        @option("--name", required=True, help="Name of the task")
        @option(
            "--executors", required=True, help="List Executors for the task as JSON"
        )
        @option(
            "--resources", required=False, help="Resources needed by the task as JSON"
        )
        @option(
            "--volumes", required=False, help="Volumes shared by the executors as JSON"
        )
        def run(
            name: str, executors: str, resources: Optional[str], volumes: Optional[str]
        ):
            """Execute a TExAM task with the provided parameters."""
            from poiesis.core.services.texam.texam import Texam

            try:
                _executors = [
                    TesExecutor(**executor) for executor in json.loads(executors)
                ]
                _resources = (
                    TesResources.model_validate(json.loads(resources))
                    if resources
                    else None
                )
                _volumes: Optional[list[str]] = json.loads(volumes) if volumes else None
            except ValidationError as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)

            console.print(f"[cyan]Executing TExAM task:[/cyan] {name}")
            asyncio.run(Texam(name, _executors, _resources, _volumes).execute())
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
        return info
