"""Running an executor with TES ``ignore_error=true``.

Executors run as init containers, and an init container that exits non-zero
fails the Pod, so the executors after it never run. An executor with
``ignore_error`` therefore runs under a POSIX shell that runs the command,
writes its exit code to the container's termination message, and exits 0:

    /bin/sh -c '"$@"; ...; exit 0' sh <command...>

The command is passed as positional arguments, so ``"$@"`` runs it as
submitted, with nothing re-quoted. Kubernetes reports the termination message
in ``state.terminated.message``, where trec and tctl read the real exit code
back (`recorded_exit_code`). Executors without ``ignore_error`` are not
wrapped: their command runs as submitted, with no shell.

The image must have ``/bin/sh``; without it the container fails to start and
the task ends in ``EXECUTOR_ERROR``, with a system log saying so
(`start_failure_log`).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SHELL = "/bin/sh"

#: Kubernetes' default ``terminationMessagePath``, set explicitly on wrapped
#: executors since the wrapper writes to it.
TERMINATION_MESSAGE_PATH = "/dev/termination-log"

_EXIT_CODE_PREFIX = "poiesis-exit-code="

SCRIPT = (
    '"$@"; rc=$?; '
    f"printf '{_EXIT_CODE_PREFIX}%d\\n' \"$rc\" > {TERMINATION_MESSAGE_PATH}; "
    "exit 0"
)

_EXIT_CODE_RE = re.compile(rf"\A{_EXIT_CODE_PREFIX}(\d+)\s*\Z")


def wrap_command(command: Sequence[str]) -> list[str]:
    """Return the container command that runs `command` with errors ignored."""
    return [SHELL, "-c", SCRIPT, "sh", *command]


def is_wrapped(command: Sequence[str] | None) -> bool:
    """True if a container `command` is one built by `wrap_command`."""
    return list(command or [])[:3] == [SHELL, "-c", SCRIPT]


def recorded_exit_code(terminated: Mapping[str, Any]) -> int | None:
    """Exit code of an executor from its ``state.terminated`` status.

    A wrapped executor exits 0 and leaves the command's exit code in the
    termination message; any other container's exit code is its own. Takes
    camelCase (watch events) or snake_case (``to_dict()``) keys.
    """
    exit_code = _exit_code(terminated)
    if exit_code == 0:
        match = _EXIT_CODE_RE.match(str(terminated.get("message") or ""))
        if match:
            return int(match.group(1))
    return exit_code


def wrapped_executor_names(pod: Mapping[str, Any]) -> frozenset[str]:
    """Names of the init containers in `pod`'s spec that `wrap_command` built."""
    spec = pod.get("spec") or {}
    containers = spec.get("initContainers") or spec.get("init_containers") or []
    return frozenset(
        c.get("name") or "" for c in containers if is_wrapped(c.get("command"))
    )


#: How container runtimes report a container whose entrypoint can't be run:
#: containerd says ``StartError`` (exit 128), Docker ``ContainerCannotRun``.
_START_FAILURE_REASONS = frozenset(
    {"StartError", "ContainerCannotRun", "RunContainerError"}
)
_START_FAILURE_EXIT_CODES = frozenset({126, 127, 128})


def start_failure_log(name: str, terminated: Mapping[str, Any]) -> str | None:
    """System log line for a wrapped executor whose shell didn't start.

    Returns None unless the container failed to start (see
    ``_START_FAILURE_REASONS``): once the shell runs, the wrapper exits 0, or
    128 + N when a signal kills it (deadline, OOM), which is not a shell
    problem.
    """
    exit_code = _exit_code(terminated)
    reason = terminated.get("reason")
    if (
        reason not in _START_FAILURE_REASONS
        and exit_code not in _START_FAILURE_EXIT_CODES
    ):
        return None
    line = (
        f"container {name} failed to start (exit code {exit_code}, {reason}); "
        f"it sets ignore_error, which runs its command under {SHELL}, so the "
        f"image must have {SHELL}"
    )
    message = str(terminated.get("message") or "").strip()
    if message:
        line += f": {message[:500]}"
    return line


def _exit_code(terminated: Mapping[str, Any]) -> int | None:
    exit_code = terminated.get("exitCode")
    if exit_code is None:
        exit_code = terminated.get("exit_code")
    return exit_code
