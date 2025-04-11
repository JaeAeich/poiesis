"""Base classes and utilities for CLI commands."""

from abc import abstractmethod
from typing import Any, TypeVar

import rich_click as click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.cli.styling import STYLE_INFO
from poiesis.cli.utils import get_basic_info, get_version
from poiesis.constants import get_poiesis_constants

console = Console()

T = TypeVar("T", bound="BaseCommand")

api_constants = get_poiesis_api_constants()
constants = get_poiesis_constants()


class BaseCommand:
    """Base class for all CLI commands."""

    name: str = "base"
    help: str = "Base command"
    description: str = "Base command description"

    @classmethod
    def register(cls: type[T], group: click.Group) -> T:
        """Register the command with a Click group.

        Args:
            group: The Click group to register with

        Returns:
            Instance of the command class
        """
        instance = cls()
        group.add_command(instance.create_command())
        return instance

    def create_command(self) -> click.Group:
        """Create a Click command group for this service.

        Returns:
            Click command group
        """

        @click.group(name=self.name, help=self.help)
        def command_group():
            pass

        self.add_info_command(command_group)
        self.add_version_command(command_group)
        self.add_run_command(command_group)

        return command_group

    def add_version_command(self, group: click.Group) -> None:
        """Add the version command to the group.

        Args:
            group: Click group to add the command to
        """

        @group.command(
            name="version", help=f"Display version of the {self.name} service"
        )
        def version():
            version_info = get_version()
            console.print(f"{self.name.upper()} Service v{version_info}")

    def add_info_command(self, group: click.Group) -> None:
        """Add the info command to the group.

        Args:
            group: Click group to add the command to
        """

        @group.command(
            name="info", help=f"Display information about the {self.name} service"
        )
        def info():
            table = Table(show_header=False, box=None)
            table.add_column("Key", style="cyan")
            table.add_column("Value", style="green")

            info_dict = self.get_info()
            for key, value in info_dict.items():
                table.add_row(str(key), str(value))

            panel = Panel(
                table,
                title=f"{self.name.upper()}",
                style=STYLE_INFO,
                border_style="cyan",
            )
            console.print(panel)

    def get_info(self) -> dict[str, Any]:
        """Get information about the service.

        Args:
            extra: Whether to include extra information

        Returns:
            Dictionary with service information
        """
        return get_basic_info()

    @abstractmethod
    def add_run_command(self, group: click.Group) -> None:
        """Add the run command to the group.

        This method should be overridden by subclasses.

        Args:
            group: Click group to add the command to
        """
        pass
