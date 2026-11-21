"""TCtl service CLI command."""

import asyncio
import os
import sys
from typing import Any

import click

from poiesis.cli.commands.poiesis.base import BaseCommand
from poiesis.core.tctl import run
from poiesis.k8s.client import load_config

#: Seconds a task may wait for its Pod to be created and scheduled. Unset:
#: it waits until the Job's time limit (`taskpods.activeDeadlineSeconds`).
_UNSCHEDULABLE_TIMEOUT_ENV = "POIESIS_TCTL_UNSCHEDULABLE_TIMEOUT_SECONDS"


class TctlCommand(BaseCommand):
    """TCtl CLI command implementation."""

    name = "tctl"
    help = "Task Controller — backstop reconciler"
    description = (
        "Leader-elected controller that polls task Jobs and TaskPods and "
        "writes every task's terminal state; the in-Pod recorder writes none."
    )

    def add_run_command(self, group: click.Group) -> None:
        """Wire `poiesis tctl run`."""

        @group.command(name="run", help="Run the TCtl reconciler")
        def run_cmd() -> None:
            namespace = _required_env("POIESIS_TASKPOD_NAMESPACE")
            # TaskPods may live in their own namespace; the leader Lease
            # stays next to tctl, where its Role grants Lease access.
            lease_namespace = os.environ.get("POIESIS_NAMESPACE") or namespace
            dsn = _required_env("DATABASE_URL")
            identity = os.environ.get("POIESIS_POD_NAME") or None
            unschedulable_timeout = _timeout_env(_UNSCHEDULABLE_TIMEOUT_ENV)
            load_config()
            click.echo(
                f"--- TCtl --- namespace={namespace} "
                f"lease-namespace={lease_namespace} identity={identity or 'auto'} "
                f"unschedulable-timeout={unschedulable_timeout or 'none'}"
            )
            sys.exit(
                asyncio.run(
                    run(
                        namespace,
                        dsn,
                        lease_namespace=lease_namespace,
                        identity=identity,
                        unschedulable_timeout=unschedulable_timeout,
                    )
                )
            )

    def get_info(self) -> dict[str, Any]:
        """Service information for `poiesis tctl info`."""
        info = super().get_info()
        info["description"] = self.description
        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
        )


def _required_env(name: str) -> str:
    """Read an env var or fail loud."""
    value = os.environ.get(name)
    if not value:
        msg = f"environment variable {name} must be set"
        raise click.ClickException(msg)
    return value


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
