"""Task persistence — free functions over an asyncpg connection.

Each function takes a `Connection` and is composable inside a caller-owned
transaction. `create_task` opens its own transaction internally because the
multi-table insert tree is a single atomic unit.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

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


class TaskView(StrEnum):
    """TES view level controlling which fields are populated on read."""

    MINIMAL = "MINIMAL"
    BASIC = "BASIC"
    FULL = "FULL"


@dataclass(frozen=True, slots=True)
class TaskScope:
    """Tasks shared with a caller beyond their own, from a decision service.

    A fixed vocabulary, turned into parameterised SQL by `list_tasks`
    and never into a raw predicate. Each dimension that is not ``None``
    must match (dimensions are joined by AND); within one, any value
    matches (values are joined by OR): the task's owner is one of
    ``owners``, its ``groups`` overlap ``groups``, its tags hold one of
    the ``tags`` (key, value) pairs. Build one only with at least one
    dimension, each with at least one value: an empty dimension matches
    nothing.
    """

    owners: tuple[str, ...] | None = None
    groups: tuple[str, ...] | None = None
    tags: tuple[tuple[str, str], ...] | None = None


@dataclass(slots=True)
class ListFilters:
    """Filters and pagination cursor for `list_tasks`.

    ``owner`` restricts the list to one owner's tasks and, if ``scope``
    is set, the tasks it matches as well (``scope`` is ignored without
    ``owner``). ``owner=None`` lists every task: internal call sites
    (workers, migrations), and the route when the decision service
    allows the caller to list all tasks.
    """

    name_prefix: str | None = None
    state: TesState | None = None
    tag_key: list[str] = field(default_factory=list)
    tag_value: list[str] = field(default_factory=list)
    page_size: int = 256
    page_token: str | None = None
    owner: str | None = None
    scope: TaskScope | None = None


# -- writes ------------------------------------------------------------------


async def create_task(
    conn: asyncpg.Connection,
    task: TesTask,
    owner: str,
    groups: Sequence[str] = (),
) -> str:
    """Persist a new task tree and return its id.

    Opens an internal transaction; the entire task aggregate inserts atomically.
    If `task.id` is unset, a UUID is generated. ``owner`` is the opaque
    owner id supplied by the API layer (``issuer|subject``, or the
    anonymous sentinel when auth is disabled). ``groups`` are the groups
    the task is shared with: set by the decision service, empty unless
    the operator enabled sharing.
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
            volumes, tags, creation_time, owner, groups
            )
            VALUES (
            $1, $2, $3, $4,
            $5, $6, $7, $8, $9,
            $10::jsonb, $11,
            $12, $13::jsonb, $14, $15, $16
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
            owner,
            list(groups),
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

        if not task.logs:
            await conn.execute(
                """
                INSERT INTO task_logs (task_id, ordinal, start_time)
                VALUES ($1, 0, now())
                """,
                uuid.UUID(task_id),
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


async def get_task(
    conn: asyncpg.Connection,
    task_id: str,
    view: TaskView = TaskView.FULL,
    owner: str | None = None,
) -> TesTask | None:
    """Fetch a task by id at the requested view level.

    Returns ``None`` if the task does not exist OR if ``owner`` is
    set and does not own the task (route handlers translate ``None`` to
    a 404, so the two cases are indistinguishable to the caller — the
    owner-only policy intentionally does not leak existence).
    ``owner=None`` is the internal-bypass case used by workers.
    """
    task_uuid = uuid.UUID(task_id)
    if owner is None:
        task_row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_uuid)
    else:
        task_row = await conn.fetchrow(
            "SELECT * FROM tasks WHERE id = $1 AND owner = $2",
            task_uuid,
            owner,
        )
    if task_row is None:
        return None

    if view is TaskView.MINIMAL:
        return _minimal_task(task_row)

    children = await _fetch_children(conn, [task_uuid])
    return _build_task(task_row, children, task_uuid, view)


async def get_task_meta(
    conn: asyncpg.Connection, task_id: str
) -> dict[str, Any] | None:
    """Return a task's ``owner``, ``state``, ``tags`` and ``groups``, or ``None``.

    No owner filter: the caller decides who may see the task.
    """
    row = await conn.fetchrow(
        "SELECT owner, state, tags, groups FROM tasks WHERE id = $1",
        uuid.UUID(task_id),
    )
    if row is None:
        return None
    return {
        "owner": row["owner"],
        "state": row["state"],
        "tags": _load_jsonb(row["tags"]) or {},
        "groups": list(row["groups"]),
    }


async def list_tasks(
    conn: asyncpg.Connection,
    filters: ListFilters,
    view: TaskView = TaskView.MINIMAL,
) -> tuple[list[TesTask], str | None]:
    """Return a page of tasks plus a `next_page_token` (or None at end-of-list).

    Page ordering is `creation_time DESC, id DESC`. The token is a base64url-
    encoded `"<rfc3339>|<uuid>"` pair pointing at the last row of the previous
    page; rows are returned strictly after that pair.
    """
    clauses, params = _build_filter_clauses(filters)
    params.append(filters.page_size + 1)

    sql_parts = [
        "SELECT id, state, name, creation_time FROM tasks"
        if view is TaskView.MINIMAL
        else "SELECT * FROM tasks"
    ]
    if clauses:
        sql_parts.append("WHERE " + " AND ".join(clauses))
    sql_parts.append("ORDER BY creation_time DESC, id DESC")
    sql_parts.append(f"LIMIT ${len(params)}")
    rows = await conn.fetch(" ".join(sql_parts), *params)

    next_token: str | None = None
    if len(rows) > filters.page_size:
        last = rows[filters.page_size - 1]
        next_token = _encode_page_token(last["creation_time"], last["id"])
        rows = rows[: filters.page_size]

    if view is TaskView.MINIMAL:
        return [_minimal_task(r) for r in rows], next_token

    # One query per child table for the whole page, not per task. No
    # owner filter: the rows already passed the visibility clause, which
    # with a scope admits other owners' tasks too.
    children = await _fetch_children(conn, [r["id"] for r in rows])
    return [_build_task(r, children, r["id"], view) for r in rows], next_token


def _minimal_task(task_row: asyncpg.Record) -> TesTask:
    """Map a task row to the MINIMAL view: its id and state only.

    TES: "Task message will include ONLY the fields: tesTask.Id,
    tesTask.State". `executors` is required by the schema, so it is an
    empty list.
    """
    return TesTask(
        id=str(task_row["id"]),
        state=TesState(task_row["state"]),
        executors=[],
        # Explicitly None: the model's default is the time of this request.
        creation_time=None,
    )


@dataclass(slots=True)
class _Children:
    """Child rows of one or more tasks, grouped by parent id, in ordinal order.

    ``inputs``, ``outputs``, ``executors`` and ``logs`` are keyed by task
    id; ``executor_logs`` by task log id.
    """

    inputs: dict[uuid.UUID, list[asyncpg.Record]] = field(default_factory=dict)
    outputs: dict[uuid.UUID, list[asyncpg.Record]] = field(default_factory=dict)
    executors: dict[uuid.UUID, list[asyncpg.Record]] = field(default_factory=dict)
    logs: dict[uuid.UUID, list[asyncpg.Record]] = field(default_factory=dict)
    executor_logs: dict[int, list[asyncpg.Record]] = field(default_factory=dict)


async def _fetch_children(
    conn: asyncpg.Connection, task_ids: Sequence[uuid.UUID]
) -> _Children:
    """Fetch the child rows of ``task_ids``: five queries, whatever their count."""
    children = _Children()
    if not task_ids:
        return children
    ids = list(task_ids)
    for sql, grouped in (
        (
            "SELECT * FROM task_inputs WHERE task_id = ANY($1::uuid[])"
            " ORDER BY task_id, ordinal",
            children.inputs,
        ),
        (
            "SELECT * FROM task_outputs WHERE task_id = ANY($1::uuid[])"
            " ORDER BY task_id, ordinal",
            children.outputs,
        ),
        (
            "SELECT * FROM task_executors WHERE task_id = ANY($1::uuid[])"
            " ORDER BY task_id, ordinal",
            children.executors,
        ),
        (
            "SELECT * FROM task_logs WHERE task_id = ANY($1::uuid[])"
            " ORDER BY task_id, ordinal",
            children.logs,
        ),
    ):
        for r in await conn.fetch(sql, ids):
            grouped.setdefault(r["task_id"], []).append(r)

    log_ids = [log["id"] for rows in children.logs.values() for log in rows]
    if log_ids:
        for r in await conn.fetch(
            """
            SELECT * FROM executor_logs
            WHERE task_log_id = ANY($1::int[])
            ORDER BY task_log_id, ordinal
            """,
            log_ids,
        ):
            children.executor_logs.setdefault(r["task_log_id"], []).append(r)
    return children


def _build_task(
    task_row: asyncpg.Record,
    children: _Children,
    task_id: uuid.UUID,
    view: TaskView,
) -> TesTask:
    """Map a task row and its child rows to a BASIC or FULL `TesTask`."""
    basic = view is TaskView.BASIC
    return TesTask(
        id=str(task_row["id"]),
        state=TesState(task_row["state"]),
        name=task_row["name"],
        description=task_row["description"],
        inputs=[
            TesInput(
                name=r["name"],
                description=r["description"],
                url=r["url"],
                path=r["path"],
                type=TesFileType(r["type"]),
                content=None if basic else r["content"],
                streamable=r["streamable"],
            )
            for r in children.inputs.get(task_id, [])
        ]
        or None,
        outputs=[
            TesOutput(
                name=r["name"],
                description=r["description"],
                url=r["url"],
                path=r["path"],
                path_prefix=r["path_prefix"],
                type=TesFileType(r["type"]),
            )
            for r in children.outputs.get(task_id, [])
        ]
        or None,
        resources=TesResources(
            cpu_cores=task_row["cpu_cores"],
            preemptible=task_row["preemptible"],
            ram_gb=task_row["ram_gb"],
            disk_gb=task_row["disk_gb"],
            zones=list(task_row["zones"]) if task_row["zones"] is not None else None,
            backend_parameters=_load_jsonb(task_row["backend_parameters"]),
            backend_parameters_strict=task_row["backend_parameters_strict"],
        ),
        executors=[
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
            for r in children.executors.get(task_id, [])
        ],
        volumes=list(task_row["volumes"]) if task_row["volumes"] is not None else None,
        tags=_load_jsonb(task_row["tags"]),
        logs=[
            TesTaskLog(
                logs=[
                    TesExecutorLog(
                        start_time=_format_dt(exr["start_time"]),
                        end_time=_format_dt(exr["end_time"]),
                        stdout=None if basic else exr["stdout"],
                        stderr=None if basic else exr["stderr"],
                        exit_code=exr["exit_code"],
                    )
                    for exr in children.executor_logs.get(log_row["id"], [])
                ],
                metadata=_load_jsonb(log_row["metadata"]),
                start_time=_format_dt(log_row["start_time"]),
                end_time=_format_dt(log_row["end_time"]),
                outputs=[
                    TesOutputFileLog(**o)
                    for o in (_load_jsonb(log_row["outputs"]) or [])
                ],
                system_logs=None
                if basic
                else (
                    list(log_row["system_logs"])
                    if log_row["system_logs"] is not None
                    else None
                ),
            )
            for log_row in children.logs.get(task_id, [])
        ]
        or None,
        creation_time=_format_dt(task_row["creation_time"]),
    )


def _build_filter_clauses(filters: ListFilters) -> tuple[list[str], list[Any]]:
    """Materialise positional WHERE clauses + parameters for `list_tasks`."""
    clauses: list[str] = []
    params: list[Any] = []

    if filters.owner is not None:
        params.append(filters.owner)
        visible = [f"owner = ${len(params)}"]
        shared = _scope_clauses(filters.scope, params)
        if shared:
            visible.append("(" + " AND ".join(shared) + ")")
        clauses.append("(" + " OR ".join(visible) + ")")
    if filters.name_prefix is not None:
        params.append(f"{_escape_like(filters.name_prefix)}%")
        clauses.append(f"name LIKE ${len(params)} ESCAPE '\\'")
    if filters.state is not None:
        params.append(filters.state.value)
        clauses.append(f"state = ${len(params)}")
    for i, key in enumerate(filters.tag_key):
        params.append(key)
        value = filters.tag_value[i] if i < len(filters.tag_value) else ""
        if value:
            # `@>` rather than `->> =` so the GIN index on tags serves it;
            # the same match, since tag values are strings.
            params[-1] = json.dumps({key: value})
            clauses.append(f"tags @> ${len(params)}::jsonb")
        else:
            clauses.append(f"tags ? ${len(params)}")
    cursor = _decode_page_token(filters.page_token)
    if cursor is not None:
        params.extend([cursor[0], cursor[1]])
        clauses.append(f"(creation_time, id) < (${len(params) - 1}, ${len(params)})")
    return clauses, params


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards in ``text`` so it matches literally.

    Backslash is the escape character, PostgreSQL's default for LIKE,
    and the query names it explicitly.
    """
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _scope_clauses(scope: TaskScope | None, params: list[Any]) -> list[str]:
    """Return one clause per dimension of ``scope``; append its parameters.

    Values are always bound as array parameters, never spliced in.
    """
    if scope is None:
        return []
    clauses: list[str] = []
    if scope.owners is not None:
        params.append(list(scope.owners))
        clauses.append(f"owner = ANY(${len(params)}::text[])")
    if scope.groups is not None:
        params.append(list(scope.groups))
        clauses.append(f"groups && ${len(params)}::text[]")
    if scope.tags is not None:
        # One single-pair object per (key, value): `@>` matches a task
        # whose tags hold that pair, ANY joins the pairs by OR.
        params.append([json.dumps({key: value}) for key, value in scope.tags])
        clauses.append(f"tags @> ANY(${len(params)}::jsonb[])")
    return clauses


def _encode_page_token(creation_time: datetime, task_id: uuid.UUID) -> str:
    raw = f"{creation_time.isoformat()}|{task_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_page_token(token: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not token:
        return None
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        ts, tid = raw.split("|", 1)
        return datetime.fromisoformat(ts), uuid.UUID(tid)
    except (ValueError, UnicodeDecodeError) as exc:
        msg = "invalid page_token"
        raise ValueError(msg) from exc


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
