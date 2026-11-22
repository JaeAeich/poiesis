"""`poiesis tof`: the task output filer."""

import asyncio
import logging
import sys

import asyncpg
import click

from poiesis.cli.env import configure_logging, required_env
from poiesis.core import filer_error
from poiesis.core.filer.tof import Tof
from poiesis.db import state as state_db
from poiesis.db import tasks as tasks_db
from poiesis.tes.models import TesOutputFileLog

logger = logging.getLogger(__name__)


@click.group(name="tof", help="Task Output Filer service")
def tof() -> None:
    """Uploads a task's outputs from the shared task volume."""


@tof.command(name="run", help="Upload a task's declared outputs")
@click.option(
    "--task-id",
    required=True,
    help="UUID of the task whose outputs should be uploaded.",
)
def run_output_filer(task_id: str) -> None:
    """Upload the task's outputs and record what was uploaded."""
    configure_logging(task_id)
    dsn = required_env("DATABASE_URL")
    logger.info("tof: starting")
    sys.exit(asyncio.run(_run(task_id, dsn)))


async def _run(task_id: str, dsn: str) -> int:
    """Fetch the task from Postgres and upload its outputs."""
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

    outputs = task.outputs or []
    if not outputs:
        logger.info("no outputs declared; nothing to upload")
        return 0

    async def record(files: list[TesOutputFileLog]) -> None:
        conn = await asyncpg.connect(dsn)
        try:
            await state_db.set_output_logs(conn, task_id, files)
        finally:
            await conn.close()

    await Tof(task_id, outputs, record).execute()
    return 0
