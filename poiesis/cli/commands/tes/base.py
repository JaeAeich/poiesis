"""Base classes and utilities for CLI commands."""

from abc import abstractmethod
from typing import TypeVar

import click

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.constants import get_poiesis_constants

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

        self.add_create_task_command(command_group)
        self.add_get_task_command(command_group)
        self.add_cancel_task_command(command_group)
        self.add_list_tasks_command(command_group)

        return command_group

    @abstractmethod
    def add_create_task_command(self, group: click.Group) -> None:
        """Add the create task command to the group.

        Args:
            group: Click group to add the command to
        """
        pass

    @abstractmethod
    def add_get_task_command(self, group: click.Group) -> None:
        """Add the get task command to the group.

        Args:
            group: Click group to add the command to
        """
        pass

    @abstractmethod
    def add_cancel_task_command(self, group: click.Group) -> None:
        """Add the cancel task command to the group.

        Args:
            group: Click group to add the command to
        """
        pass

    @abstractmethod
    def add_list_tasks_command(self, group: click.Group) -> None:
        """Add the list tasks command to the group.

        Args:
            group: Click group to add the command to
        """
        pass
