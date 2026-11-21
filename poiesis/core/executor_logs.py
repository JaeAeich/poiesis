"""Read the output of a finished executor.

TES serves ``logs[].logs[].stdout`` and ``stderr`` from ``executor_logs``.
The kubelet keeps the log of a terminated container for as long as its Pod
exists, so trec (as each executor finishes) and tctl (when it backfills)
read the last ``MAX_OUTPUT_BYTES`` of ``exec-N``'s log and store it.

The container log mixes stdout and stderr, so all of it is stored as
``stdout``. An executor that sets TES ``stdout`` or ``stderr`` writes that
stream to a file instead (see `executor_shell`), and the container log no
longer has it. When the file is on the task volume, trec, which mounts the
volume, reads its tail instead (`read_executor_streams`); the container log
then fills the stream that isn't redirected. tctl doesn't mount task
volumes, so its backfill has only the container log.

A failed read never fails the task: the reader logs a warning and returns
None, and the row is stored without that output.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import posixpath
import stat
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from poiesis.core.constants import EXECUTOR_STREAMS_ENV, FILER_PVC_PATH

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kubernetes.client import CoreV1Api

logger = logging.getLogger(__name__)

#: How much of the end of an executor's log is kept.
MAX_OUTPUT_BYTES = 64 * 1024
_CHUNK_BYTES = 16 * 1024
#: Lines asked of the kubelet, which reads them from the end of the log, so
#: a huge log isn't sent whole; the bytes are then trimmed here.
_TAIL_LINES = 4096
#: (connect, read) timeouts so a stuck API server can't hold the recorder.
_REQUEST_TIMEOUT_SECONDS = (10, 30)


async def read_executor_output(
    core_v1: CoreV1Api,
    pod_name: str,
    namespace: str,
    ordinal: int,
) -> str | None:
    """Return the last `MAX_OUTPUT_BYTES` of `exec-<ordinal>`'s log, or None.

    None means the log could not be read; the reason is logged as a
    warning. Never raises.
    """
    container = f"exec-{ordinal}"
    try:
        raw = await asyncio.to_thread(
            _read_tail, core_v1, pod_name, namespace, container
        )
    except Exception as exc:  # noqa: BLE001 - a log read must never fail the task
        logger.warning(
            "could not read the log of %s in pod %s/%s: %s",
            container,
            namespace,
            pod_name,
            exc,
        )
        return None
    return _to_text(raw)


def _read_tail(
    core_v1: CoreV1Api, pod_name: str, namespace: str, container: str
) -> bytes:
    """Stream the container log and keep only its last `MAX_OUTPUT_BYTES`.

    The log API's ``limitBytes`` keeps the *start* of a log, so only the
    last ``_TAIL_LINES`` lines are asked for, and the response is streamed
    and trimmed here; memory stays bounded however long the log is.
    """
    # The stubs don't list the client's `_preload_content`/`_request_timeout`.
    api: Any = core_v1
    response = api.read_namespaced_pod_log(
        name=pod_name,
        namespace=namespace,
        container=container,
        tail_lines=_TAIL_LINES,
        _preload_content=False,
        _request_timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    tail = bytearray()
    try:
        for chunk in response.stream(_CHUNK_BYTES):
            tail += chunk
            if len(tail) > MAX_OUTPUT_BYTES:
                del tail[: len(tail) - MAX_OUTPUT_BYTES]
    finally:
        response.release_conn()
    return bytes(tail)


@dataclass(frozen=True)
class Streams:
    """The streams of one executor that go to files, and where trec finds them.

    Attributes:
        redirected: ``stdout`` and/or ``stderr``, the TES fields it sets.
        files: For each redirected stream whose file is on the task volume,
            the file's path under ``FILER_PVC_PATH``. Missing when the file
            is elsewhere in the executor's container and gone with it.
    """

    redirected: frozenset[str]
    files: Mapping[str, str] = field(default_factory=dict)

    def without_files(self) -> Streams:
        """The same streams, for a reader that can't see the task volume."""
        return Streams(self.redirected)


def encode_streams(streams: Mapping[int, Streams]) -> str:
    """`streams` as the value of ``EXECUTOR_STREAMS_ENV``, set on trec."""
    return json.dumps(
        {
            str(ordinal): {s: entry.files.get(s) for s in sorted(entry.redirected)}
            for ordinal, entry in sorted(streams.items())
        },
        separators=(",", ":"),
    )


def decode_streams(value: str | None) -> dict[int, Streams]:
    """Read back `encode_streams`; empty for no value or a bad one."""
    if not value:
        return {}
    try:
        raw = json.loads(value)
        return {
            int(ordinal): Streams(
                frozenset(entry),
                {s: path for s, path in entry.items() if isinstance(path, str)},
            )
            for ordinal, entry in raw.items()
        }
    except (ValueError, TypeError, AttributeError) as exc:
        logger.warning("ignoring a bad %s: %s", EXECUTOR_STREAMS_ENV, exc)
        return {}


def streams_from_pod(pod: Mapping[str, Any]) -> dict[int, Streams]:
    """The `Streams` trec was given, from the trec container of `pod`'s spec."""
    spec = pod.get("spec") or {}
    for container in spec.get("initContainers") or spec.get("init_containers") or []:
        if container.get("name") != "trec":
            continue
        for env in container.get("env") or []:
            if env.get("name") == EXECUTOR_STREAMS_ENV:
                return decode_streams(env.get("value"))
    return {}


async def read_executor_streams(
    core_v1: CoreV1Api,
    pod_name: str,
    namespace: str,
    ordinal: int,
    streams: Streams | None = None,
) -> tuple[str | None, str | None]:
    """Return ``(stdout, stderr)`` of `exec-<ordinal>`, each None if unknown.

    Without `streams`, the container log is the stdout. Otherwise each
    redirected stream comes from its file on the task volume, and the
    container log, which holds the rest, fills the first stream left
    without output: the one not redirected, or one whose file couldn't be
    read (the shell's own error, e.g. a file it couldn't create, is there).
    Never raises.
    """
    log = await read_executor_output(core_v1, pod_name, namespace, ordinal)
    if streams is None or not streams.redirected:
        return log, None
    output: dict[str, str | None] = {"stdout": None, "stderr": None}
    read_files: set[str] = set()
    for stream in ("stdout", "stderr"):
        path = streams.files.get(stream)
        if stream not in streams.redirected or path is None:
            continue
        if path in read_files:
            continue  # stderr written to the stdout file: already in stdout
        read_files.add(path)
        output[stream] = await read_volume_file(path)
    unredirected = [s for s in ("stdout", "stderr") if s not in streams.redirected]
    for stream in unredirected or ["stdout", "stderr"]:
        if output[stream] is None and (unredirected or log):
            output[stream] = log
            break
    return output["stdout"], output["stderr"]


async def read_volume_file(path: str, root: str = FILER_PVC_PATH) -> str | None:
    """Return the last `MAX_OUTPUT_BYTES` of a file on the task volume, or None.

    `path` is below `root`, where the task volume is mounted. None means the
    file could not be read; the reason is logged as a warning. Never raises.
    """
    try:
        raw = await asyncio.to_thread(_read_file_tail, path, root)
    except Exception as exc:  # noqa: BLE001 - a log read must never fail the task
        logger.warning("could not read executor output file %s: %s", path, exc)
        return None
    return _to_text(raw)


def _read_file_tail(path: str, root: str) -> bytes:
    """Read the end of `path`, a regular file below `root`.

    The executor that wrote the file runs user code, and the reader may
    hold credentials, so no symlink is followed, in the path or at its
    end: each directory is opened relative to the last one with
    ``O_NOFOLLOW``. Anything but a regular file is refused.
    """
    relative = posixpath.relpath(posixpath.normpath(path), root)
    parts = relative.split("/")
    if relative.startswith("..") or "" in parts or "." in parts:
        msg = f"{path} is not below {root}"
        raise ValueError(msg)
    nofollow = os.O_RDONLY | os.O_NOFOLLOW
    dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, nofollow | os.O_DIRECTORY, dir_fd=dir_fd)
            os.close(dir_fd)
            dir_fd = next_fd
        file_fd = os.open(parts[-1], nofollow | os.O_NONBLOCK, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)
    with os.fdopen(file_fd, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode):
            msg = f"{path} is not a regular file"
            raise ValueError(msg)
        file.seek(max(0, info.st_size - MAX_OUTPUT_BYTES))
        return file.read(MAX_OUTPUT_BYTES)


def _to_text(raw: bytes) -> str:
    """Decode log bytes for a Postgres TEXT column.

    Trimming may cut a UTF-8 sequence and executors may print anything,
    so bad bytes are replaced; NUL, which TEXT can't hold, is dropped.
    """
    return raw.decode("utf-8", errors="replace").replace("\x00", "")
