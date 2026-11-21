"""Why a filer failed, carried in its container's termination message.

A filer (tif or tof) that fails exits non-zero, which alone says nothing of
the cause, and the Pod's logs go with its Job. So before exiting, the filer
writes one line saying what failed to its termination message, which
Kubernetes keeps in ``state.terminated.message`` for as long as the Pod
exists. tctl reads it back (`cause`), copies it to the task's system logs
and picks the task's terminal state from it.

A filer failure is the system's: storage that can't be reached, a rejected
or expired URL, denied access, a full volume. The task ends in
``SYSTEM_ERROR``.

A declared output the executors didn't produce is the user's
(`MissingOutputError`). The line starts with a marker and the task ends in
``EXECUTOR_ERROR``.

The line is at most `MAX_BYTES` long and carries no query string and no
credentials of a URL, since a presigned URL's query is its signature.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from poiesis.core.ignore_error import TERMINATION_MESSAGE_PATH

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

#: Longest cause written or read, in bytes of UTF-8. Kubernetes keeps up to
#: 4096 bytes of a termination message.
MAX_BYTES = 1024

_USER_ERROR_PREFIX = "poiesis-user-error: "

#: A query string: `?` up to the next space, quote or angle bracket, with a
#: `=` in it, so the `?` of a glob or a sentence is left alone. A value that
#: was cut before (`<redacted>`) is part of it.
_QUERY_CHAR = r"(?:<redacted>|[^\s'\"<>])"
_QUERY_RE = re.compile(rf"\?{_QUERY_CHAR}*={_QUERY_CHAR}*")
#: The `user:password@` of a URL.
_USERINFO_RE = re.compile(r"(?<=://)[^/\s'\"<>@]+@")


class MissingOutputError(FileNotFoundError):
    """A declared output isn't on the task's volume as declared.

    The executors didn't produce it, so the failure is the user's.
    """


def sanitise(text: str) -> str:
    """Return `text` as one line of at most `MAX_BYTES`, without secrets.

    Query strings and the credentials of URLs are cut.
    """
    line = "".join(c for c in " ".join(text.split()) if c.isprintable())
    line = _QUERY_RE.sub("?<redacted>", line)
    line = _USERINFO_RE.sub("<redacted>@", line)
    return line.encode()[:MAX_BYTES].decode(errors="ignore")


def describe(error: BaseException) -> str:
    """One line saying what `error` is, with the notes added to it.

    The filers note which input or output they were handling (PEP 678
    ``add_note``); the notes come first.
    """
    if isinstance(error, MissingOutputError):
        return sanitise(str(error))
    message = str(error)
    parts = [
        *getattr(error, "__notes__", ()),
        f"{type(error).__name__}: {message}" if message else type(error).__name__,
    ]
    return sanitise(": ".join(parts))


def write(cause: str, *, user_error: bool = False) -> None:
    """Write `cause` as the container's termination message.

    Never raises: outside a container there is no such file, and a filer
    that can't report why it failed still has to exit non-zero.
    """
    line = sanitise((_USER_ERROR_PREFIX if user_error else "") + cause)
    path = TERMINATION_MESSAGE_PATH
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.warning("Could not write the termination message to %s: %s", path, e)


def record(error: BaseException) -> None:
    """Write why the filer failed with `error` as its termination message."""
    write(describe(error), user_error=isinstance(error, MissingOutputError))


def cause(terminated: Mapping[str, Any]) -> tuple[str, bool] | None:
    """The cause a filer left in its ``state.terminated`` status.

    Returns the line and whether the failure is the user's, or None if the
    filer left no message, as when it was killed.
    """
    message = sanitise(str(terminated.get("message") or ""))
    if not message:
        return None
    if message.startswith(_USER_ERROR_PREFIX):
        return message.removeprefix(_USER_ERROR_PREFIX), True
    return message, False
