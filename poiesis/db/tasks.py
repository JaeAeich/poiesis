"""Task persistence — free functions over an asyncpg connection.

Each function takes a `Connection` and is composable inside a caller-owned
transaction. `create_task` opens its own transaction internally because the
multi-table insert tree is a single atomic unit.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg

from poiesis.api.tes.models import (
    TesExecutor,
    TesExecutorLog,
    TesFileType,
    TesInput,
    TesOutput,
    TesOutputFileLog,
    TesResources,
    TesState,
    TesTask,
    TesTaskLog,
)

# -- writes ------------------------------------------------------------------


async def create_task(conn: asyncpg.Connection, task: TesTask) -> str:
    """Persist a new task tree and return its id.

    Opens an internal transaction; the entire task aggregate inserts atomically.
    If `task.id` is unset, a UUID is generated.
    """
    task_id = task.id or str(uuid.uuid4())
    resources = task.resources or TesResources()

    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO tasks (
            id, state, name, description,
            cpu_cores, preemptible, ram_gb, disk_gb, zones,
            backend_parameters, backend_parameters_strict,
            volumes, tags, creation_time
            )
            VALUES (
            $1, $2, $3, $4,
            $5, $6, $7, $8, $9,
            $10::jsonb, $11,
            $12, $13::jsonb, $14
            )
            """,
            uuid.UUID(task_id),
            (task.state or TesState.UNKNOWN).value,
            task.name,
            task.description,
            resources.cpu_cores,
            resources.preemptible,
            resources.ram_gb,
            resources.disk_gb,
            resources.zones,
            _dumps(resources.backend_parameters),
            bool(resources.backend_parameters_strict),
            task.volumes,
            _dumps(task.tags),
            _parse_dt(task.creation_time),
        )

        for idx, inp in enumerate(task.inputs or []):
            await conn.execute(
                """
                INSERT INTO task_inputs (
                task_id, ordinal, name, description,
                url, path, type, content, streamable
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                uuid.UUID(task_id),
                idx,
                inp.name,
                inp.description,
                inp.url,
                inp.path,
                (inp.type or TesFileType.FILE).value,
                inp.content,
                inp.streamable,
            )

        for idx, out in enumerate(task.outputs or []):
            await conn.execute(
                """
                INSERT INTO task_outputs (
                task_id, ordinal, name, description,
                url, path, path_prefix, type
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                uuid.UUID(task_id),
                idx,
                out.name,
                out.description,
                out.url,
                out.path,
                out.path_prefix,
                (out.type or TesFileType.FILE).value,
            )

        for idx, ex in enumerate(task.executors):
            await conn.execute(
                """
                INSERT INTO task_executors (
                task_id, ordinal, image, command,
                workdir, stdin, stdout, stderr, env, ignore_error
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
                """,
                uuid.UUID(task_id),
                idx,
                ex.image,
                ex.command,
                ex.workdir,
                ex.stdin,
                ex.stdout,
                ex.stderr,
                _dumps(ex.env),
                ex.ignore_error,
            )

        for log_idx, log in enumerate(task.logs or []):
            task_log_id: int = await conn.fetchval(
                """
                INSERT INTO task_logs (
                task_id, ordinal, metadata, start_time, end_time,
                system_logs, outputs
                )
                VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7::jsonb)
                RETURNING id
                """,
                uuid.UUID(task_id),
                log_idx,
                _dumps(log.metadata),
                _parse_dt(log.start_time),
                _parse_dt(log.end_time),
                log.system_logs,
                json.dumps([o.model_dump(mode="json") for o in (log.outputs or [])]),
            )
            for ex_idx, exlog in enumerate(log.logs or []):
                await conn.execute(
                    """
                    INSERT INTO executor_logs (
                    task_log_id, ordinal, start_time, end_time,
                    stdout, stderr, exit_code
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    task_log_id,
                    ex_idx,
                    _parse_dt(exlog.start_time),
                    _parse_dt(exlog.end_time),
                    exlog.stdout,
                    exlog.stderr,
                    exlog.exit_code,
                )

    return task_id


# -- reads -------------------------------------------------------------------


async def get_task(conn: asyncpg.Connection, task_id: str) -> TesTask | None:
    """Fetch a task by id, fully reconstructed. Returns None if not found."""
    row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", uuid.UUID(task_id))
    if row is None:
        return None

    inputs = await conn.fetch(
        "SELECT * FROM task_inputs WHERE task_id = $1 ORDER BY ordinal", row["id"]
    )
    outputs = await conn.fetch(
        "SELECT * FROM task_outputs WHERE task_id = $1 ORDER BY ordinal", row["id"]
    )
    executors = await conn.fetch(
        "SELECT * FROM task_executors WHERE task_id = $1 ORDER BY ordinal", row["id"]
    )
    logs = await conn.fetch(
        "SELECT * FROM task_logs WHERE task_id = $1 ORDER BY ordinal", row["id"]
    )

    executor_logs_by_log: dict[int, list[asyncpg.Record]] = {}
    if logs:
        rows = await conn.fetch(
            """
            SELECT * FROM executor_logs
            WHERE task_log_id = ANY($1::int[])
            ORDER BY task_log_id, ordinal
            """,
            [log["id"] for log in logs],
        )
        for r in rows:
            executor_logs_by_log.setdefault(r["task_log_id"], []).append(r)

    return _row_to_task(row, inputs, outputs, executors, logs, executor_logs_by_log)


# -- internal mapping helpers ------------------------------------------------


def _parse_dt(value: str | None) -> datetime | None:
    """Parse a TES RFC3339 timestamp; Python 3.11+ handles trailing Z natively."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _format_dt(value: datetime | None) -> str | None:
    """Format a datetime as an RFC3339 string matching TES wire shape."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S%z")


def _dumps(value: Any) -> str | None:
    """JSON-encode for asyncpg JSONB parameters, treating None as NULL."""
    return None if value is None else json.dumps(value)


def _load_jsonb(value: Any) -> Any:
    """Asyncpg returns JSONB as a Python str unless a codec is registered."""
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_task(  # noqa: PLR0913 - private assembler; one caller; row sets are intentionally separate fetches
    task_row: asyncpg.Record,
    input_rows: list[asyncpg.Record],
    output_rows: list[asyncpg.Record],
    executor_rows: list[asyncpg.Record],
    log_rows: list[asyncpg.Record],
    executor_logs_by_log: dict[int, list[asyncpg.Record]],
) -> TesTask:
    """Reconstruct a TesTask from its relational rows."""
    resources = TesResources(
        cpu_cores=task_row["cpu_cores"],
        preemptible=task_row["preemptible"],
        ram_gb=task_row["ram_gb"],
        disk_gb=task_row["disk_gb"],
        zones=list(task_row["zones"]) if task_row["zones"] is not None else None,
        backend_parameters=_load_jsonb(task_row["backend_parameters"]),
        backend_parameters_strict=task_row["backend_parameters_strict"],
    )

    inputs = [
        TesInput(
            name=r["name"],
            description=r["description"],
            url=r["url"],
            path=r["path"],
            type=TesFileType(r["type"]),
            content=r["content"],
            streamable=r["streamable"],
        )
        for r in input_rows
    ]
    outputs = [
        TesOutput(
            name=r["name"],
            description=r["description"],
            url=r["url"],
            path=r["path"],
            path_prefix=r["path_prefix"],
            type=TesFileType(r["type"]),
        )
        for r in output_rows
    ]
    executors = [
        TesExecutor(
            image=r["image"],
            command=list(r["command"]),
            workdir=r["workdir"],
            stdin=r["stdin"],
            stdout=r["stdout"],
            stderr=r["stderr"],
            env=_load_jsonb(r["env"]),
            ignore_error=r["ignore_error"],
        )
        for r in executor_rows
    ]
    logs = [
        TesTaskLog(
            logs=[
                TesExecutorLog(
                    start_time=_format_dt(exr["start_time"]),
                    end_time=_format_dt(exr["end_time"]),
                    stdout=exr["stdout"],
                    stderr=exr["stderr"],
                    exit_code=exr["exit_code"],
                )
                for exr in executor_logs_by_log.get(log_row["id"], [])
            ],
            metadata=_load_jsonb(log_row["metadata"]),
            start_time=_format_dt(log_row["start_time"]),
            end_time=_format_dt(log_row["end_time"]),
            outputs=[
                TesOutputFileLog(**o) for o in (_load_jsonb(log_row["outputs"]) or [])
            ],
            system_logs=list(log_row["system_logs"])
            if log_row["system_logs"] is not None
            else None,
        )
        for log_row in log_rows
    ]

    return TesTask(
        id=str(task_row["id"]),
        state=TesState(task_row["state"]),
        name=task_row["name"],
        description=task_row["description"],
        inputs=inputs or None,
        outputs=outputs or None,
        resources=resources,
        executors=executors,
        volumes=list(task_row["volumes"]) if task_row["volumes"] is not None else None,
        tags=_load_jsonb(task_row["tags"]),
        logs=logs or None,
        creation_time=_format_dt(task_row["creation_time"]),
    )
