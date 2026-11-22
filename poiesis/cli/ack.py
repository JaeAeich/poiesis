"""`poiesis ack`: the terminal container in every TaskPod.

Init containers (TIF, executors, TOF) carry the real work; `ack` runs after
they finish, prints a single completion line, and exits 0 so the Pod reaches
`Succeeded`.

Reusing the poiesis image here avoids a second image pull per TaskPod.
The output is a kubelet-captured log line for `kubectl logs` debugging —
not a TES audit record.
"""

import click


@click.group(name="ack", help="Terminal container that closes a TaskPod")
def ack() -> None:
    """The container that closes a TaskPod."""


@ack.command(name="run", help="Acknowledge that init containers finished")
@click.option("--task-id", required=True, help="UUID of the task this Pod ran.")
def run(task_id: str) -> None:
    """Print the completion line and exit 0."""
    click.echo(f"ack: task={task_id}")
