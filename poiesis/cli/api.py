"""`poiesis api`: the TES API server."""

import click

from poiesis.api.asgi import run as serve_api


@click.group(name="api", help="API server management")
def api() -> None:
    """The TES API server."""


@api.command(name="run", help="Start the API server")
def run() -> None:
    """Start the Poiesis API server."""
    click.echo("Starting Poiesis API server ...")
    serve_api()
