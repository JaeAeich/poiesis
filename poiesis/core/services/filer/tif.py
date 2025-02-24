"""Entry point for the TIF service."""

import argparse
import json

from pydantic import ValidationError

from poiesis.api.tes.models import TesInput
from poiesis.core.ports.message_broker import Message
from poiesis.core.services.filer.filer import Filer
from poiesis.core.services.filer.filer_strategy_factory import FilerStrategyFactory


class Tif(Filer):
    """Task input filer.

    Args:
        name: Name of the task.
        inputs: List of task inputs.

    Attributes:
        name: Name of the task.
        inputs: List of task inputs.
        message_broker: Message broker.
    """

    def __init__(self, name: str, inputs: list[TesInput]):
        """Task input filer.

        Args:
            name: Name of the task.
            inputs: List of task inputs.

        Attributes:
            name: Name of the task.
            inputs: List of task inputs.
            message_broker: Message broker.
        """
        self.name = name
        self.inputs = input

    def file(self):
        """Filing logic, download."""
        for input in self.inputs:
            filer_strategy = FilerStrategyFactory.create_strategy(input.url)
            try:
                filer_strategy.download(input)
            except Exception as e:
                self.message(Message(f"TIF failed: {e}"))
                raise


def main() -> None:
    """Entry point for the TIF service.

    Command Line Arguments:
        --name: The name of the task
        --inputs: A JSON string containing list of inputs from the TES task request.

    Returns:
        None

    Raises:
        JSONDecodeError: If the provided input cannot be parsed as valid JSON
        ValidationError: If the input data doesn't match the TesInput schema
        Exception: For any other unexpected errors

    Example:
        Command line usage:
        ```bash
        $ tif --name md5sum --inputs '[{
            "url": "s3://my-object-store/file1",
            "path": "/data/file1"
        }]'
        ```

        Multiple inputs:
        ```bash
        $ tif --name image-processor --inputs '[
            {
                "url": "s3://my-object-store/file1",
                "path": "/data/file1"
            },
            {
                "url": "file://local/file2",
                "path": "/data/file2"
            }
        ]'
        ```
    """
    parser = argparse.ArgumentParser(description="TIF service command line interface.")
    parser.add_argument("--name", nargs="+", required=True, help="Name of the task.")
    parser.add_argument(
        "--inputs", nargs="+", required=True, help="List of task inputs."
    )
    args = parser.parse_args()

    try:
        input_str = " ".join(args.inputs)
        _inputs = json.loads(input_str)
        inputs = [TesInput(**input_) for input_ in _inputs]
        Tif(args.name, inputs).execute()
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        raise
    except ValidationError as e:
        print(f"Validation error: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise
