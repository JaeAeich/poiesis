"""Poiesis CLI main entry point."""

import click

from poiesis.cli.commands.poiesis.api import ApiCommand
from poiesis.cli.commands.poiesis.tif import TifCommand
from poiesis.cli.commands.poiesis.tof import TofCommand
from poiesis.cli.commands.poiesis.trec import TrecCommand
from poiesis.cli.utils import get_basic_info, get_version


@click.group(help="Poiesis is a GA4GH TES compliant task execution service")
@click.version_option(get_version(), prog_name="Poiesis")
def cli():
    """Poiesis CLI main entry point."""


@cli.command(name="info", help="Display information about all Poiesis services")
def info():
    """Display information about all Poiesis services."""
    info_data = get_basic_info()
    info_data.update(
        {
            "description": "GA4GH TES compliant task execution service",
        }
    )

    info_data = dict(
        sorted({k.replace("_", " ").title(): v for k, v in info_data.items()}.items())
    )

    title = f"Poiesis v{get_version()}"
    click.echo(title)
    click.echo("-" * len(title))

    for key, value in info_data.items():
        click.echo(f"{key}: {value}")


def main():
    """Main entry point for the CLI."""
    ApiCommand.register(cli)
    TifCommand.register(cli)
    TofCommand.register(cli)
    TrecCommand.register(cli)

    cli()
