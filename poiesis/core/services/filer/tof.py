"""Entry point for the TOF service."""

import argparse
import json

from pydantic import ValidationError

from poiesis.api.tes.models import TesOutput
from poiesis.core.ports.message_broker import Message
from poiesis.core.services.filer.filer import Filer
from poiesis.core.services.filer.filer_strategy_factory import FilerStrategyFactory


class Tof(Filer):
    """Task output filer.

    Args:
        name: Name of the task.
        outputs: List of task outputs.

    Attributes:
        name: Name of the task.
        outputs: List of task outputs.
        message_broker: Message broker
    """

    def __init__(self, name: str, outputs: list[TesOutput]):
        """Task output filer.

        Args:
            name: Name of the task.
            outputs: List of task outputs.

        Attributes:
            name: Name of the task.
            outputs: List of task outputs.
            message_broker: Message broker
        """
        self.name = name
        self.outputs = outputs

    def file(self):
        """Filing logic, upload."""
        for output in self.outputs:
            filer_strategy = FilerStrategyFactory.create_strategy(output.url)
            try:
                filer_strategy.upload(output)
            except Exception as e:
                self.message(Message(f"TOF failed: {e}"))
                raise


def main() -> None:
    """Entry point for the TOF service.

    Command Line Arguments:
        --name: The name of the task.
        --outputs: A JSON string containing list of outputs from the TES task request.

    Returns:
        None

    Raises:
        JSONDecodeError: If the provided input cannot be parsed as valid JSON
        ValidationError: If the output data doesn't match the TesOutput schema
        Exception: For any other unexpected errors

    Example:
        Command line usage:
        ```bash
        $ tof --name md5sum --outputs '[{
            "path": "/data/outfile",
            "url": "s3://my-object-store/outfile-1",
            "type": "FILE"
        }]'
        ```

        Multiple outputs:
        ```bash
        $ tof --name image-processor --outputs '[
            {
                "path": "/data/outfile1",
                "url": "s3://my-object-store/outfile-1",
                "type": "FILE"
            },
            {
                "path": "/data/outfile2",
                "url": "file:///data/outfile-2",
                "type": "FILE"
            }
        ]'
        ```
    """
    parser = argparse.ArgumentParser(description="TIF service command line interface.")
    parser.add_argument("--name", nargs="+", required=True, help="Name of the task.")
    parser.add_argument(
        "--outputs", nargs="+", required=True, help="List of task outputs."
    )
    args = parser.parse_args()

    try:
        output_str = " ".join(args.outputs)
        _outputs = json.loads(output_str)
        outputs = [TesOutput(**output) for output in _outputs]
        Tof(args.name, outputs).execute()
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        raise
    except ValidationError as e:
        print(f"Validation error: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise
