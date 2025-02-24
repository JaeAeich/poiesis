"""Entrypoint for TExAM service."""

import argparse
import json
import logging
from typing import Optional

from pydantic import ValidationError

from poiesis.api.tes.models import TesExecutor, TesResources
from poiesis.core.services.texam.texam import Texam

logger = logging.getLogger(__name__)


async def main() -> None:
    """Entrypoint for the TExAM service.

    This module provides the command-line interface for the Task Executor and Monitor
    (TExAM) service, which is responsible for executing and monitoring TES (Task
    Execution Service) tasks on Kubernetes infrastructure.

    Returns:
        None

    Raises:
        JSONDecodeError: If the provided input cannot be parsed as valid JSON.
        ValidationError: If the input data doesn't match the TesInput schema.
        Exception: For any other unexpected errors.

    Example:
        Command line usage:
        ```bash
        $ texam --name "md5sum-task"
            --executors
            '[{"image":"ubuntu:20.04","command":["/bin/md5sum","/data/file1"]}]'
            --resources '{"cpu_cores":1,"ram_gb":2,"disk_gb":10}'
            --volumes '["/shared-data"]'
        ```

        Complex example:
        ```bash
        $ texam --name "complex-analysis" --executors '[{
            "image": "ubuntu:20.04",
            "command": ["/bin/md5", "/data/file1"],
            "workdir": "/data/",
            "stdin": "/data/file1",
            "stdout": "/tmp/stdout.log",
            "stderr": "/tmp/stderr.log",
            "env": {
                "BLASTDB": "/data/GRC38",
                "HMMERDB": "/data/hmmer"
            },
            "ignore_error": true
        }]' --resources '{
            "cpu_cores": 4,
            "preemptible": false,
            "ram_gb": 8,
            "disk_gb": 40,
            "zones": ["us-west-1"],
            "backend_parameters": {
                "VmSize": "Standard_D64_v3"
            },
            "backend_parameters_strict": false
        }' --volumes '["/vol/A/"]'
        ```
    """
    parser = argparse.ArgumentParser(
        description="Task executor and monitor (TExAM) service."
    )
    parser.add_argument("--name", nargs="+", required=True, help="Name of the task.")
    parser.add_argument(
        "--executors", nargs="+", required=True, help="Executors for the task."
    )
    parser.add_argument("--resources", nargs="+", help="Resources needed by the task.")
    parser.add_argument("--volumes", nargs="+", help="Volume shared by the executors.")
    args = parser.parse_args()

    try:
        name = args.name
        executors = [TesExecutor(**executor) for executor in json.loads(args.executors)]
        resources = (
            TesResources.model_validate(args.resources) if args.resources else None
        )
        volumes: Optional[list[str]] = (
            json.loads(args.volumes) if args.volumes else None
        )
        await Texam(name, executors, resources, volumes).execute()
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {e}")
        raise
    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise
