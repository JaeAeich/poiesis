"""The Prometheus ``/metrics`` endpoint of the API and of tctl.

Each process serves the default registry on its own port
(``POIESIS_METRICS_PORT``), apart from the TES API's port: the endpoint is
never reached through the Ingress, needs no auth and is not in the access
log. The API runs one process per Pod (`poiesis.api.asgi`), so one
process owns every metric and no multiprocess mode is needed.

Labels are bounded: no task id, user or owner is ever a label value.
"""

from __future__ import annotations

import logging
import os
import socketserver
import threading
from typing import TYPE_CHECKING, Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from prometheus_client import disable_created_metrics, make_wsgi_app

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

#: Port of the ``/metrics`` endpoint. Unset or empty: no endpoint.
METRICS_PORT_ENV = "POIESIS_METRICS_PORT"

_MAX_PORT = 65535


def metrics_port_from_env() -> int | None:
    """The metrics port from ``POIESIS_METRICS_PORT``; None if unset or empty.

    Strict: any value other than an integer in 1..65535 raises ValueError.
    """
    raw = os.environ.get(METRICS_PORT_ENV, "").strip()
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError:
        port = 0
    if not 1 <= port <= _MAX_PORT:
        msg = f"{METRICS_PORT_ENV} must be an integer in 1..{_MAX_PORT}, got {raw!r}"
        raise ValueError(msg)
    return port


class _Server(socketserver.ThreadingMixIn, WSGIServer):
    """A threaded WSGI server that binds without a DNS lookup."""

    daemon_threads = True

    def server_bind(self) -> None:
        """Bind; unlike `http.server`, don't look up the host's FQDN.

        That reverse lookup can take seconds, and it runs on the event loop.
        """
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)
        self.setup_environ()


class _QuietHandler(WSGIRequestHandler):
    """No line per scrape on stderr."""

    def log_message(self, format: str, *args: Any) -> None:
        """Log nothing."""


def serve(port: int, addr: str = "0.0.0.0") -> Callable[[], None]:  # noqa: S104
    """Serve the default registry at ``http://<addr>:<port>/metrics``.

    Runs in a daemon thread beside the event loop. Returns a function that
    stops the server. The ``*_created`` series of counters and histograms
    are left out: they double the series and no query here needs them.
    """
    disable_created_metrics()
    server = make_server(
        addr, port, make_wsgi_app(), _Server, handler_class=_QuietHandler
    )
    thread = threading.Thread(
        target=server.serve_forever, name="poiesis-metrics", daemon=True
    )
    thread.start()
    logger.info("Serving Prometheus metrics on %s:%d", addr, port)

    def stop() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    return stop
