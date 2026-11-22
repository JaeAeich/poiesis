"""`poiesis trec`: the task recorder sidecar."""

import asyncio
import logging
import os
import sys

import click

from poiesis.cli.env import configure_logging, required_env
from poiesis.core.constants import EXECUTOR_STREAMS_ENV
from poiesis.core.executor_logs import decode_streams
from poiesis.core.trec import run
from poiesis.k8s.client import load_config

logger = logging.getLogger(__name__)


@click.group(name="trec", help="Task Recorder sidecar")
def trec() -> None:
    """Watches its own Pod and records the task's lifecycle to the database."""


@trec.command(name="run", help="Record the surrounding Pod's lifecycle")
@click.option("--task-id", required=True, help="UUID of the task this Pod is running.")
def run_recorder(task_id: str) -> None:
    """Read trec's settings from the environment and record until the Pod ends."""
    configure_logging(task_id)
    pod_name = required_env("POIESIS_POD_NAME")
    namespace = required_env("POIESIS_POD_NAMESPACE")
    dsn = required_env("DATABASE_URL")
    streams = decode_streams(os.environ.get(EXECUTOR_STREAMS_ENV))
    load_config()
    logger.info("trec: starting; pod=%s/%s", pod_name, namespace)
    sys.exit(asyncio.run(run(task_id, pod_name, namespace, dsn, streams)))
