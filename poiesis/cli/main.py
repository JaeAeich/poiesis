"""The ``poiesis`` command: one subcommand per Poiesis process."""

import click

from poiesis.cli.ack import ack
from poiesis.cli.api import api
from poiesis.cli.tctl import tctl
from poiesis.cli.tif import tif
from poiesis.cli.tof import tof
from poiesis.cli.trec import trec


@click.group(help="Poiesis is a GA4GH TES compliant task execution service")
@click.version_option(package_name="poiesis", prog_name="Poiesis")
def cli() -> None:
    """Poiesis CLI main entry point."""


for command in (api, tctl, trec, tif, tof, ack):
    cli.add_command(command)


def main() -> None:
    """Entry point of the ``poiesis`` console script."""
    cli()
