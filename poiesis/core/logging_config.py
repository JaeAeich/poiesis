"""Logging setup shared by the API, tctl, trec, tif and tof.

Every line goes to stderr. When stderr isn't a terminal (a container),
each line is one JSON object: ``timestamp`` (RFC 3339 UTC), ``level``,
``logger``, ``message``, the ``request_id`` (API) and ``task_id`` (trec,
tif, tof, and tctl lines about one task) when set, ``exception`` when
there is one, and the fields a call passes in ``extra``. On a terminal,
lines are plain text with a coloured level. ``POIESIS_LOG_FORMAT``
(``json`` or ``text``) forces one or the other.

The audit log (``poiesis.audit``) has a handler and format of its own
and is not affected.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from collections.abc import Iterator


#: Forces the log format: ``json`` or ``text``. Unset or empty: JSON
#: unless stderr is a terminal.
LOG_FORMAT_ENV = "POIESIS_LOG_FORMAT"
LOG_FORMATS = ("json", "text")

#: The request id of the API request being served (set by the API's
#: request id middleware).
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "poiesis_request_id", default=None
)
_task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "poiesis_task_id", default=None
)
#: The task of a process that serves one task (trec, tif, tof): seen by
#: every thread, unlike a context variable.
_process_task_id: str | None = None

# ANSI escape codes for colors
LOG_COLORS = {
    "DEBUG": "\033[94m",  # Blue
    "INFO": "\033[92m",  # Green
    "WARNING": "\033[93m",  # Yellow
    "ERROR": "\033[91m",  # Red
    "CRITICAL": "\033[95m",  # Magenta
    "RESET": "\033[0m",  # Reset
}

#: Attributes every LogRecord has; anything else came from ``extra``
#: (except uvicorn's ``color_message``: its message with ANSI codes).
_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "request_id",
    "task_id",
    "color_message",
}


def set_task_id(task_id: str) -> None:
    """Tag every later line of this process with ``task_id``."""
    global _process_task_id  # noqa: PLW0603 (one task per process)
    _process_task_id = task_id


@contextmanager
def task_context(task_id: str) -> Iterator[None]:
    """Tag the lines logged inside the block with ``task_id``."""
    token = _task_id_var.set(task_id)
    try:
        yield
    finally:
        _task_id_var.reset(token)


class ContextFilter(logging.Filter):
    """Adds ``request_id`` and ``task_id`` (or ``None``) to each record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Set the ids; never drops a record."""
        record.request_id = request_id_var.get()
        record.task_id = _task_id_var.get() or _process_task_id
        return True


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    """The fields a call passed in ``extra``."""
    return {
        key: value
        for key, value in vars(record).items()
        if key not in _RECORD_ATTRS and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """One JSON object per record, on one line."""

    def format(self, record: logging.LogRecord) -> str:
        """Format ``record`` as JSON; ids that aren't set are left out."""
        line: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "task_id"):
            value = getattr(record, key, None)
            if value is not None:
                line[key] = value
        line |= _extras(record)
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            line["stack"] = self.formatStack(record.stack_info)
        return json.dumps(line, separators=(",", ":"), default=str)


class ColorFormatter(logging.Formatter):
    """Human-readable lines with a coloured level, for a terminal."""

    def __init__(self) -> None:
        """Use the time, level, logger and message."""
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def formatMessage(self, record: logging.LogRecord) -> str:
        """Colour the level and append the ids and extra fields."""
        level = record.levelname
        colored = f"{LOG_COLORS.get(level, '')}{level}{LOG_COLORS['RESET']}"
        text = super().formatMessage(record).replace(level, colored, 1)
        fields = {
            key: getattr(record, key, None) for key in ("request_id", "task_id")
        } | _extras(record)
        pairs = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
        return f"{text} [{pairs}]" if pairs else text


class _Handler(logging.StreamHandler):
    """The handler :func:`setup_logging` installs (so it can replace it)."""


def resolve_format(value: str | None, stream: TextIO) -> str:
    """The log format: ``value`` if set, else ``text`` on a terminal, else ``json``.

    Raises:
        ValueError: ``value`` is set but not a known format.
    """
    value = (value or "").strip().lower()
    if value:
        if value not in LOG_FORMATS:
            msg = (
                f"{LOG_FORMAT_ENV} must be one of {', '.join(LOG_FORMATS)}, "
                f"got {value!r}"
            )
            raise ValueError(msg)
        return value
    isatty = getattr(stream, "isatty", None)
    return "text" if isatty is not None and isatty() else "json"


def setup_logging(
    level: str | None = None,
    log_format: str | None = None,
    stream: TextIO | None = None,
) -> None:
    """Send every logger's lines to ``stream`` (stderr) in one format.

    Args:
        level: Logging level; defaults to ``LOG_LEVEL`` (INFO).
        log_format: ``json`` or ``text``; defaults to ``POIESIS_LOG_FORMAT``,
            else chosen by whether ``stream`` is a terminal.
        stream: Where lines go; defaults to stderr.
    """
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    stream = stream or sys.stderr
    if log_format is None:
        log_format = os.environ.get(LOG_FORMAT_ENV)
    try:
        chosen = resolve_format(log_format, stream)
    except ValueError as exc:
        chosen = "json"
        warning: str | None = f"{exc}; using json"
    else:
        warning = None

    handler = _Handler(stream)
    handler.setFormatter(JsonFormatter() if chosen == "json" else ColorFormatter())
    handler.addFilter(ContextFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # Replacing our own handler only: a test's log capture stays.
    for old in [h for h in root_logger.handlers if isinstance(h, _Handler)]:
        root_logger.removeHandler(old)
    root_logger.addHandler(handler)

    # Lines of the core module and of the servers (gunicorn, uvicorn) go
    # through the root handler.
    for name in ("poiesis.core", "gunicorn.error", "uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("poiesis.core").setLevel(level)
    if warning is not None:
        logging.getLogger(__name__).warning("%s", warning)
