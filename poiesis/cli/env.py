"""What every Poiesis command reads from its environment at startup."""

import os

import click

from poiesis.core.logging_config import (
    LOG_FORMAT_ENV,
    resolve_format,
    set_task_id,
    setup_logging,
)


def configure_logging(task_id: str | None = None) -> None:
    """Set up logging from ``POIESIS_LOG_FORMAT``; tag lines with ``task_id``.

    Strict: an unknown format stops the command at startup.
    """
    raw = os.environ.get(LOG_FORMAT_ENV)
    try:
        resolve_format(raw, click.get_text_stream("stderr"))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    setup_logging(log_format=raw)
    if task_id is not None:
        set_task_id(task_id)


def required_env(name: str) -> str:
    """Read an env var; stop the command if it is unset or empty."""
    value = os.environ.get(name)
    if not value:
        msg = f"environment variable {name} must be set"
        raise click.ClickException(msg)
    return value
