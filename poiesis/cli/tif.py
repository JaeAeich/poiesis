"""`poiesis tif`: the task input filer."""

import asyncio
import logging
import sys

import asyncpg
import click

from poiesis.cli.env import configure_logging, required_env
from poiesis.core import filer_error
from poiesis.core.services.filer.tif import Tif
from poiesis.db import tasks as tasks_db

logger = logging.getLogger(__name__)


@click.group(name="tif", help="Task Input Filer service")
def tif() -> None:
    """Stages a task's inputs onto the shared task volume."""


@tif.command(name="run", help="Download a task's declared inputs")
@click.option(
    "--task-id", required=True, help="UUID of the task whose inputs should be staged."
)
@click.option(
    "--mkdir",
    "dirs",
    multiple=True,
    help="Executor path of a directory to create after staging; repeatable.",
)
def run_input_filer(task_id: str, dirs: tuple[str, ...]) -> None:
    """Stage the task's inputs, then create ``dirs``."""
    configure_logging(task_id)
    dsn = required_env("DATABASE_URL")
    logger.info("tif: starting")
    sys.exit(asyncio.run(_run(task_id, dsn, dirs)))


async def _run(task_id: str, dsn: str, dirs: tuple[str, ...] = ()) -> int:
    """Fetch the task from Postgres, stage its inputs and create `dirs`."""
    try:
        conn = await asyncpg.connect(dsn)
        try:
            task = await tasks_db.get_task(conn, task_id, view=tasks_db.TaskView.FULL)
        finally:
            await conn.close()
    except Exception as e:
        # The cause reaches the task's system logs through the container's
        # termination message, as a failed transfer's does.
        e.add_note("reading the task from the database")
        filer_error.record(e)
        raise

    if task is None:
        logger.error("task %s not found", task_id)
        filer_error.write(f"task {task_id} not found in the database")
        return 1

    inputs = task.inputs or []
    if not inputs and not dirs:
        logger.info("no inputs declared; nothing to stage")
        return 0

    await Tif(task_id, inputs, dirs).execute()
    return 0
