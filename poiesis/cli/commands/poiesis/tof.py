"""TOF service CLI command."""

import asyncio
import os
import sys
from typing import Any

import asyncpg
import click

from poiesis.cli.commands.poiesis.base import BaseCommand
from poiesis.core.services.filer.filer_strategy_factory import (
    supported_output_schemes,
)
from poiesis.core.services.filer.tof import Tof
from poiesis.db import tasks as tasks_db


class TofCommand(BaseCommand):
    """TOF CLI command implementation."""

    name = "tof"
    help = "Task Output Filer service"
    description = "Upload TES task outputs from the shared task volume."

    def add_run_command(self, group: click.Group) -> None:
        """Wire `poiesis tof run --task-id <id>`."""

        @group.command(name="run", help="Upload a task's declared outputs")
        @click.option(
            "--task-id",
            required=True,
            help="UUID of the task whose outputs should be uploaded.",
        )
        def run_cmd(task_id: str) -> None:
            dsn = _required_env("DATABASE_URL")
            click.echo(f"--- TOF --- task={task_id}")
            sys.exit(asyncio.run(_run(task_id, dsn)))

    def get_info(self) -> dict[str, Any]:
        """Service information for `poiesis tof info`."""
        info = super().get_info()
        info.update(
            {
                "description": self.description,
                "supported_protocols": ", ".join(supported_output_schemes()),
            }
        )
        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
        )


async def _run(task_id: str, dsn: str) -> int:
    """Fetch the task from Postgres and upload its outputs."""
    conn = await asyncpg.connect(dsn)
    try:
        task = await tasks_db.get_task(conn, task_id, view=tasks_db.TaskView.FULL)
    finally:
        await conn.close()

    if task is None:
        click.echo(f"task {task_id} not found", err=True)
        return 1

    outputs = task.outputs or []
    if not outputs:
        click.echo("no outputs declared; nothing to upload")
        return 0

    await Tof(task_id, outputs).execute()
    return 0


def _required_env(name: str) -> str:
    """Read an env var or fail loud."""
    value = os.environ.get(name)
    if not value:
        msg = f"environment variable {name} must be set"
        raise click.ClickException(msg)
    return value
