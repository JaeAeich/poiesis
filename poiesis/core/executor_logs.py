"""Read the output of a finished executor from its container log.

TES serves ``logs[].logs[].stdout`` from ``executor_logs.stdout``. The
kubelet keeps the log of a terminated container for as long as its Pod
exists, so trec (as each executor finishes) and tctl (when it backfills)
read the last ``MAX_OUTPUT_BYTES`` of ``exec-N``'s log and store it.

The container log mixes stdout and stderr, so all of it is stored as
``stdout``. A failed read never fails the task: the reader logs a warning
and returns None, and the row is stored without output.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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


def _to_text(raw: bytes) -> str:
    """Decode log bytes for a Postgres TEXT column.

    Trimming may cut a UTF-8 sequence and executors may print anything,
    so bad bytes are replaced; NUL, which TEXT can't hold, is dropped.
    """
    return raw.decode("utf-8", errors="replace").replace("\x00", "")
