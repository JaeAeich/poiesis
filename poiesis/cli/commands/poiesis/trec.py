"""TRec service CLI command."""

import asyncio
import os
import sys
from typing import Any

import click

from poiesis.cli.commands.poiesis.base import BaseCommand
from poiesis.core.trec import run
from poiesis.k8s.client import load_config


class TrecCommand(BaseCommand):
    """TRec CLI command implementation."""

    name = "trec"
    help = "Task Recorder sidecar"
    description = (
        "Watches the surrounding Pod via the Kubernetes API and records "
        "task lifecycle transitions to the database."
    )

    def add_run_command(self, group: click.Group) -> None:
        """Wire `poiesis trec run --task-id <id>`."""

        @group.command(name="run", help="Record the surrounding Pod's lifecycle")
        @click.option(
            "--task-id",
            required=True,
            help="UUID of the task this Pod is running.",
        )
        def run_cmd(task_id: str) -> None:
            pod_name = _required_env("POIESIS_POD_NAME")
            namespace = _required_env("POIESIS_POD_NAMESPACE")
            dsn = _required_env("POSTGRES_DSN")
            load_config()
            click.echo(f"--- TRec --- task={task_id} pod={pod_name}/{namespace}")
            exit_code = asyncio.run(run(task_id, pod_name, namespace, dsn))
            sys.exit(exit_code)

    def get_info(self) -> dict[str, Any]:
        """Service information for `poiesis trec info`."""
        info = super().get_info()
        info["description"] = self.description
        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items()),
        )


def _required_env(name: str) -> str:
    """Read an env var or fail loud."""
    value = os.environ.get(name)
    if not value:
        msg = f"environment variable {name} must be set"
        raise click.ClickException(msg)
    return value
