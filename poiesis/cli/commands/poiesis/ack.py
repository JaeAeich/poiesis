"""Ack service CLI command.

The terminal container in every TaskPod. Init containers (TIF, executors,
TOF) carry the real work; `ack` runs after they finish, prints a single
completion line, and exits 0 so the Pod reaches `Succeeded`.

Reusing the poiesis image here avoids a second image pull per TaskPod.
The output is a kubelet-captured log line for `kubectl logs` debugging —
not a TES audit record.
"""

from typing import Any

import click

from poiesis.cli.commands.poiesis.base import BaseCommand


class AckCommand(BaseCommand):
    """Ack CLI command implementation."""

    name = "ack"
    help = "Terminal container that closes a TaskPod"
    description = (
        "Runs as the TaskPod's regular container after every init "
        "container finishes; exits 0 so the Pod reaches Succeeded."
    )

    def add_run_command(self, group: click.Group) -> None:
        """Wire `poiesis ack run`."""

        @group.command(name="run", help="Acknowledge that init containers finished")
        @click.option(
            "--task-id",
            required=True,
            help="UUID of the task this Pod ran.",
        )
        def run_cmd(task_id: str) -> None:
            click.echo(f"ack: task={task_id}")

    def get_info(self) -> dict[str, Any]:
        """Service information for `poiesis ack info`."""
        info = super().get_info()
        info["description"] = self.description
        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
        )
