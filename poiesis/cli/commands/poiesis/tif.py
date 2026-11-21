"""TIF service CLI command."""

import asyncio
import os
import sys
from typing import Any

import asyncpg
import click

from poiesis.cli.commands.poiesis.base import BaseCommand
from poiesis.core.services.filer.filer_strategy_factory import (
    supported_input_schemes,
)
from poiesis.core.services.filer.tif import Tif
from poiesis.db import tasks as tasks_db


class TifCommand(BaseCommand):
    """TIF CLI command implementation."""

    name = "tif"
    help = "Task Input Filer service"
    description = "Stage TES task inputs onto the shared task volume."

    def add_run_command(self, group: click.Group) -> None:
        """Wire `poiesis tif run --task-id <id>`."""

        @group.command(name="run", help="Download a task's declared inputs")
        @click.option(
            "--task-id",
            required=True,
            help="UUID of the task whose inputs should be staged.",
        )
        @click.option(
            "--mkdir",
            "dirs",
            multiple=True,
            help="Executor path of a directory to create after staging; repeatable.",
        )
        def run_cmd(task_id: str, dirs: tuple[str, ...]) -> None:
            dsn = _required_env("DATABASE_URL")
            click.echo(f"--- TIF --- task={task_id}")
            sys.exit(asyncio.run(_run(task_id, dsn, dirs)))

    def get_info(self) -> dict[str, Any]:
        """Service information for `poiesis tif info`."""
        info = super().get_info()
        info.update(
            {
                "description": self.description,
                "supported_protocols": ", ".join(supported_input_schemes()),
            }
        )
        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
        )


async def _run(task_id: str, dsn: str, dirs: tuple[str, ...] = ()) -> int:
    """Fetch the task from Postgres, stage its inputs and create `dirs`."""
    conn = await asyncpg.connect(dsn)
    try:
        task = await tasks_db.get_task(conn, task_id, view=tasks_db.TaskView.FULL)
    finally:
        await conn.close()

    if task is None:
        click.echo(f"task {task_id} not found", err=True)
        return 1

    inputs = task.inputs or []
    if not inputs and not dirs:
        click.echo("no inputs declared; nothing to stage")
        return 0

    await Tif(task_id, inputs, dirs).execute()
    return 0


def _required_env(name: str) -> str:
    """Read an env var or fail loud."""
    value = os.environ.get(name)
    if not value:
        msg = f"environment variable {name} must be set"
        raise click.ClickException(msg)
    return value
