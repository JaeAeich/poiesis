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
(`executor_shell.start_failure_log`). An executor that also sets ``stdin``,
``stdout`` or ``stderr`` gets one wrapper for both (see `executor_shell`).
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

#: Records the exit code of the command just run, then exits 0.
RECORD_EXIT_CODE = (
    "rc=$?; "
    f"printf '{_EXIT_CODE_PREFIX}%d\\n' \"$rc\" > {TERMINATION_MESSAGE_PATH}; "
    "exit 0"
)

SCRIPT = f'"$@"; {RECORD_EXIT_CODE}'

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
    exit_code = terminated_exit_code(terminated)
    if exit_code == 0:
        match = _EXIT_CODE_RE.match(str(terminated.get("message") or ""))
        if match:
            return int(match.group(1))
    return exit_code


def terminated_exit_code(terminated: Mapping[str, Any]) -> int | None:
    """``exitCode`` of a ``state.terminated`` status, in either key style."""
    exit_code = terminated.get("exitCode")
    if exit_code is None:
        exit_code = terminated.get("exit_code")
    return exit_code
