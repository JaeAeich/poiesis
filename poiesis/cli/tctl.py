"""`poiesis tctl`: the task controller."""

import asyncio
import logging
import os
import sys
from pathlib import Path

import click

from poiesis.cli.env import configure_logging, required_env
from poiesis.core.metrics import metrics_port_from_env
from poiesis.core.tctl import run
from poiesis.k8s.client import load_config

logger = logging.getLogger(__name__)

#: Seconds a task may wait for its Pod to be created and scheduled. Unset:
#: it waits until the Job's time limit (`taskpods.activeDeadlineSeconds`).
_UNSCHEDULABLE_TIMEOUT_ENV = "POIESIS_TCTL_UNSCHEDULABLE_TIMEOUT_SECONDS"
#: File tctl touches after each loop iteration, for a liveness probe. Unset:
#: no heartbeat is written.
_HEARTBEAT_FILE_ENV = "POIESIS_TCTL_HEARTBEAT_FILE"
#: Seconds a database statement may run, shared with the API. Unset: 30.
_COMMAND_TIMEOUT_ENV = "POIESIS_DATABASE_COMMAND_TIMEOUT_SECONDS"
_DEFAULT_COMMAND_TIMEOUT_SECONDS = 30


@click.group(name="tctl", help="Task Controller — backstop reconciler")
def tctl() -> None:
    """Leader-elected controller that writes every task's terminal state.

    Polls task Jobs and TaskPods; the in-Pod recorder writes no terminal
    state.
    """


@tctl.command(name="run", help="Run the TCtl reconciler")
def run_reconciler() -> None:
    """Read tctl's settings from the environment and run the control loop."""
    configure_logging()
    namespace = required_env("POIESIS_TASKPOD_NAMESPACE")
    # TaskPods may live in their own namespace; the leader Lease
    # stays next to tctl, where its Role grants Lease access.
    lease_namespace = os.environ.get("POIESIS_NAMESPACE") or namespace
    dsn = required_env("DATABASE_URL")
    identity = os.environ.get("POIESIS_POD_NAME") or None
    unschedulable_timeout = _timeout_env(_UNSCHEDULABLE_TIMEOUT_ENV)
    heartbeat = _path_env(_HEARTBEAT_FILE_ENV)
    command_timeout = (
        _timeout_env(_COMMAND_TIMEOUT_ENV) or _DEFAULT_COMMAND_TIMEOUT_SECONDS
    )
    try:
        metrics_port = metrics_port_from_env()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    load_config()
    logger.info(
        "tctl: starting; namespace=%s lease-namespace=%s identity=%s "
        "unschedulable-timeout=%s heartbeat=%s db-command-timeout=%ss "
        "metrics-port=%s",
        namespace,
        lease_namespace,
        identity or "auto",
        unschedulable_timeout or "none",
        heartbeat or "none",
        command_timeout,
        metrics_port or "none",
    )
    sys.exit(
        asyncio.run(
            run(
                namespace,
                dsn,
                lease_namespace=lease_namespace,
                identity=identity,
                unschedulable_timeout=unschedulable_timeout,
                heartbeat=heartbeat,
                command_timeout=command_timeout,
                metrics_port=metrics_port,
            )
        )
    )


def _timeout_env(name: str) -> int | None:
    """Read a timeout in seconds: unset or empty is None, else an integer >= 1.

    Strict: a typo must not decide which queued tasks are failed, so any
    other value stops tctl at startup.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        seconds = int(raw)
    except ValueError:
        seconds = 0
    if seconds < 1:
        msg = f"environment variable {name} must be an integer >= 1, got {raw!r}"
        raise click.ClickException(msg)
    return seconds


def _path_env(name: str) -> Path | None:
    """Read a file path: unset or empty is None, else an absolute path.

    Strict: a relative path would depend on the working directory, which
    the liveness probe doesn't share.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        msg = f"environment variable {name} must be an absolute path, got {raw!r}"
        raise click.ClickException(msg)
    return path
