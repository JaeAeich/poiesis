"""Entry point of the Torc service."""

import argparse
import json

from pydantic import ValidationError

from poesis.api.tes.models import TesTask
from poesis.core.services.torc.torc import Torc


def main():
    """Start the Torc service via commandline input.

    The task request is sent as json string via commandline input.
    """
    parser = argparse.ArgumentParser(description="TES task request as json string.")
    parser.add_argument("task", type=str, help="TES task request as json string.")
    args = parser.parse_args()

    try:
        data = json.loads(args.task)
        task = TesTask(**data)
    except ValidationError:
        raise

    torc = Torc(task)
    torc.execute()


if __name__ == "__main__":
    main()
