"""Base classes and utilities for CLI commands."""

import os
from abc import abstractmethod
from typing import Any, Self

import click

from poiesis.cli.utils import get_basic_info, get_version
from poiesis.core.logging_config import (
    LOG_FORMAT_ENV,
    resolve_format,
    set_task_id,
    setup_logging,
)


def configure_logging(task_id: str | None = None) -> None:
    """Set up logging from ``POIESIS_LOG_FORMAT``; tag lines with ``task_id``.

    Strict: an unknown format stops the command at startup.
    """
    raw = os.environ.get(LOG_FORMAT_ENV)
    try:
        resolve_format(raw, click.get_text_stream("stderr"))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    setup_logging(log_format=raw)
    if task_id is not None:
        set_task_id(task_id)


class BaseCommand:
    """Base class for all CLI commands."""

    name: str = "base"
    help: str = "Base command"
    description: str = "Base command description"

    @classmethod
    def register(cls, group: click.Group) -> Self:
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
            click.echo(f"{self.name.upper()} Service v{version_info}")

    def add_info_command(self, group: click.Group) -> None:
        """Add the info command to the group.

        Args:
            group: Click group to add the command to
        """

        @group.command(
            name="info", help=f"Display information about the {self.name} service"
        )
        def info():
            info_dict = self.get_info()
            title = f"--- {self.name.upper()} ---"
            click.echo(title)
            for key, value in info_dict.items():
                click.echo(f"{key}: {value}")
            click.echo("-" * len(title))

    def get_info(self) -> dict[str, Any]:
        """Get information about the service.

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
