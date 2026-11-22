"""Running an executor under ``/bin/sh``, for what Kubernetes can't do.

Executors run as submitted, with no shell, so images without one work.
Two TES features need a shell, and only executors that use them get one.
With ``ignore_error`` (see `ignore_error`), the shell records the command's
exit code in the termination message and exits 0. ``stdin``, ``stdout``
and ``stderr`` are paths in the container to read stdin from and to write
stdout and stderr to; Kubernetes can't connect a container's streams to
files, so the shell opens them:

    /bin/sh -c '# poiesis: stdout stderr
    [ -d "$3" ] || mkdir -p -- "$3"
    o=$1 e=$2
    shift 3
    exec "$@" >"$o" 2>"$e"' sh /mnt/task/stdout /mnt/task/stderr /mnt/task cmd...

The paths and the command are positional arguments, so nothing is
re-quoted or expanded, and ``exec`` replaces the shell with the command,
which keeps its PID, signals and exit code. The parent directory of
``stdout`` and ``stderr`` is created if missing. With ``ignore_error``
too, the last line runs the command without ``exec`` and records its exit
code instead, as `ignore_error.SCRIPT` does. The first line names what
the shell is for; `wrapped_executors` reads it back.

The image must have ``/bin/sh`` (and ``mkdir`` when a parent directory is
missing). Without the shell the container can't start and the task ends in
``EXECUTOR_ERROR``, with a system log saying why (`start_failure_log`).
"""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING, Any

from poiesis.core import ignore_error
from poiesis.core.ignore_error import SHELL

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from poiesis.tes.models import TesExecutor

#: The TES executor fields that are files the shell opens, in this order.
STREAMS = ("stdin", "stdout", "stderr")
IGNORE_ERROR = "ignore_error"

_MARKER = "# poiesis:"
#: Shell variable per stream, set before the positional arguments shift.
_VARIABLE = {"stdin": "i", "stdout": "o", "stderr": "e"}
_REDIRECT = {"stdin": "<", "stdout": ">", "stderr": "2>"}


def streams(executor: TesExecutor) -> dict[str, str]:
    """The ``stdin``/``stdout``/``stderr`` paths `executor` sets, by field."""
    return {s: path for s in STREAMS if (path := getattr(executor, s))}


def wrap(executor: TesExecutor) -> list[str] | None:
    """The container command that runs `executor`, or None to run it as is."""
    paths = streams(executor)
    if not paths:
        if executor.ignore_error:
            return ignore_error.wrap_command(executor.command)
        return None
    script, args = _script(paths, ignore_errors=bool(executor.ignore_error))
    return [SHELL, "-c", script, "sh", *args, *executor.command]


def _script(paths: Mapping[str, str], *, ignore_errors: bool) -> tuple[str, list[str]]:
    """The wrapper script, and the arguments it takes before the command."""
    features = [s for s in STREAMS if s in paths]
    if ignore_errors:
        features.append(IGNORE_ERROR)

    args: list[str] = []
    assignments: list[str] = []
    redirects: list[str] = []
    for stream in STREAMS:
        path = paths.get(stream)
        if path is None:
            continue
        if stream == "stderr" and path == paths.get("stdout"):
            # Opening the file twice would make the two streams overwrite
            # each other.
            redirects.append("2>&1")
            continue
        args.append(path)
        assignments.append(f"{_VARIABLE[stream]}=${len(args)}")
        redirects.append(f'{_REDIRECT[stream]}"${_VARIABLE[stream]}"')

    lines = [f"{_MARKER} {' '.join(features)}"]
    for directory in _parent_dirs(paths):
        args.append(directory)
        lines.append(f'[ -d "${len(args)}" ] || mkdir -p -- "${len(args)}"')
    lines.append(" ".join(assignments))
    lines.append(f"shift {len(args)}")
    command = f'"$@" {" ".join(redirects)}'
    if ignore_errors:
        lines.append(f"{command}; {ignore_error.RECORD_EXIT_CODE}")
    else:
        lines.append(f"exec {command}")
    return "\n".join(lines), args


def _parent_dirs(paths: Mapping[str, str]) -> list[str]:
    """Directories of the ``stdout`` and ``stderr`` files, without repeats."""
    dirs: list[str] = []
    for stream in ("stdout", "stderr"):
        path = paths.get(stream)
        parent = posixpath.dirname(path) if path else ""
        if parent not in ("", "/") and parent not in dirs:
            dirs.append(parent)
    return dirs


def features(command: Sequence[str] | None) -> tuple[str, ...]:
    """What a container `command` built by `wrap` runs a shell for.

    Empty for a command that isn't wrapped.
    """
    command = list(command or [])
    if ignore_error.is_wrapped(command):
        return (IGNORE_ERROR,)
    if len(command) < 3 or command[:2] != [SHELL, "-c"]:  # noqa: PLR2004
        return ()
    first_line = command[2].split("\n", 1)[0]
    if not first_line.startswith(_MARKER):
        return ()
    return tuple(first_line.removeprefix(_MARKER).split())


def wrapped_executors(pod: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Init containers in `pod`'s spec that `wrap` built, with their features."""
    spec = pod.get("spec") or {}
    containers = spec.get("initContainers") or spec.get("init_containers") or []
    wrapped: dict[str, tuple[str, ...]] = {}
    for container in containers:
        found = features(container.get("command"))
        if found:
            wrapped[container.get("name") or ""] = found
    return wrapped


#: How container runtimes report a container whose entrypoint can't be run:
#: containerd says ``StartError`` (exit 128), Docker ``ContainerCannotRun``.
_START_FAILURE_REASONS = frozenset(
    {"StartError", "ContainerCannotRun", "RunContainerError"}
)
#: Exit codes that, for an ``ignore_error`` wrapper, also mean the shell
#: didn't run: once it runs, it exits 0 (or 128 + N on a signal).
_START_FAILURE_EXIT_CODES = frozenset({126, 127, 128})


def start_failure_log(
    name: str, terminated: Mapping[str, Any], wrapped_for: Sequence[str]
) -> str | None:
    """System log line for a wrapped executor whose shell didn't start.

    `wrapped_for` is what `features` returned for the container. Returns
    None unless the container failed to start. Exit codes alone count
    only with ``ignore_error``: a wrapper that ``exec``s the command exits
    with the command's code, and 127 then means the command wasn't found.
    """
    exit_code = ignore_error.terminated_exit_code(terminated)
    reason = terminated.get("reason")
    failed_to_start = reason in _START_FAILURE_REASONS or (
        IGNORE_ERROR in wrapped_for and exit_code in _START_FAILURE_EXIT_CODES
    )
    if not failed_to_start:
        return None
    executor = name.removeprefix("exec-")
    line = (
        f"container {name} failed to start (exit code {exit_code}, {reason}); "
        f"executor {executor} sets {', '.join(wrapped_for)}, which needs "
        f"{SHELL} in its image"
    )
    message = str(terminated.get("message") or "").strip()
    if message:
        line += f": {message[:500]}"
    return line
