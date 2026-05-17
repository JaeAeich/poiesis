"""TCtl service CLI command."""

import asyncio
import os
import sys
from typing import Any

import click

from poiesis.cli.commands.poiesis.base import BaseCommand
from poiesis.core.tctl import run
from poiesis.k8s.client import load_config


class TctlCommand(BaseCommand):
    """TCtl CLI command implementation."""

    name = "tctl"
    help = "Task Controller — backstop reconciler"
    description = (
        "Leader-elected controller that watches TaskPods and writes "
        "terminal state for failures the in-Pod recorder cannot self-report."
    )

    def add_run_command(self, group: click.Group) -> None:
        """Wire `poiesis tctl run`."""

        @group.command(name="run", help="Run the TCtl reconciler")
        def run_cmd() -> None:
            namespace = _required_env("POIESIS_TASKPOD_NAMESPACE")
            dsn = _required_env("DATABASE_URL")
            identity = os.environ.get("POIESIS_POD_NAME") or None
            load_config()
            click.echo(
                f"--- TCtl --- namespace={namespace} identity={identity or 'auto'}"
            )
            sys.exit(asyncio.run(run(namespace, dsn, identity=identity)))

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
