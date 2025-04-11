"""Poiesis CLI main entry point."""

import rich_click as click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.cli.commands.poiesis.api import ApiCommand
from poiesis.cli.commands.poiesis.texam import TexamCommand
from poiesis.cli.commands.poiesis.tif import TifCommand
from poiesis.cli.commands.poiesis.tof import TofCommand
from poiesis.cli.commands.poiesis.torc import TorcCommand
from poiesis.cli.commands.tes.task import TaskCommand
from poiesis.cli.styling import STYLE_INFO
from poiesis.cli.utils import get_basic_info, get_version
from poiesis.constants import get_poiesis_constants

api_constants = get_poiesis_api_constants()
constants = get_poiesis_constants()

console = Console()


@click.group(help="Poiesis is a GA4GH TES compliant task execution service")
@click.version_option(get_version(), prog_name="Poiesis")
def cli():
    """Poiesis CLI main entry point."""
    pass


@cli.command(name="info", help="Display information about all Poiesis services")
def info():
    """Display information about all Poiesis services."""
    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    info = get_basic_info()
    info.update(
        {
            "description": "GA4GH TES compliant task execution service",
        }
    )

    info = dict(
        sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
    )

    for key, value in sorted(info.items()):
        table.add_row(str(key), str(value))

    panel = Panel(
        table,
        title=f"Poiesis v{get_version()}",
        style=STYLE_INFO,
        border_style="cyan",
    )
    console.print(panel)


def main():
    """Main entry point for the CLI."""
    # Poiesis services
    ApiCommand.register(cli)
    TexamCommand.register(cli)
    TifCommand.register(cli)
    TofCommand.register(cli)
    TorcCommand.register(cli)

    # TES commands
    TaskCommand.register(cli)

    cli()
