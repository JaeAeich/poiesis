"""API service CLI commands."""

import os
from typing import Any

import rich_click as click
from rich.console import Console

from poiesis.api.asgi import run as api_run
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.cli.base import BaseCommand
from poiesis.constants import get_poiesis_constants

api_constants = get_poiesis_api_constants()
constants = get_poiesis_constants()


console = Console()


class ApiCommand(BaseCommand):
    """API CLI command implementation."""

    name = "api"
    help = "API server management"
    description = "Commands to run the API server and display API information."

    def add_run_command(self, group: click.Group) -> None:
        """Add API run command.

        Args:
            group: Click group to add the command to
        """

        @group.command(name="run", help="Start the API server")
        def run():
            """Start the Poiesis API server."""
            url = f"http://{api_constants.Gunicorn.HOST}:{api_constants.Gunicorn.PORT}/{api_constants.BASE_PATH}/ui"
            console.print(
                "[cyan]Starting Poiesis API server, checkout "
                f"[green]{url}[green] ...[/cyan]"
            )
            api_run()

    def get_info(self) -> dict[str, Any]:
        """Get API service information.

        Args:
            extra: Whether to include extra information

        Returns:
            Dictionary with API service information
        """
        info = super().get_info()

        host = api_constants.Gunicorn.HOST
        port = api_constants.Gunicorn.PORT
        base_path = api_constants.BASE_PATH
        url = f"http://{host}:{port}/{base_path}"
        workers = api_constants.Gunicorn.WORKERS or f"{(os.cpu_count() or 1) * 2 + 1}"

        info.update(
            {
                "description": "API service for GA4GH TES compliant task execution",
                "api": url,
                "swagger": f"{url}/ui",
                "uvicorn_workers": workers,
                "server_timeout": api_constants.Gunicorn.TIMEOUT,
            }
        )

        return dict(
            sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
        )
