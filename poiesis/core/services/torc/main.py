"""Entry point of the Torc service."""

import argparse
import asyncio
import json

from pydantic import ValidationError

from poiesis.api.tes.models import TesTask
from poiesis.core.services.torc.torc import Torc


async def async_main():
    """Start the Torc service via commandline input.

    The task request is sent as json string via commandline input.
    """
    parser = argparse.ArgumentParser(description="TES task request as json string.")
    parser.add_argument("task", type=str, help="TES task request as json string.")
    args = parser.parse_args()

    try:
        data = json.loads(args.task)
        task = TesTask(**data)
    except ValidationError as e:
        print(f"Validation error: {e}")
        raise

    torc = Torc(task)
    await torc.execute()


def main():
    """Entry point that runs the async main function."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
