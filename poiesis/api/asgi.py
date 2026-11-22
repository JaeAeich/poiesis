"""Runs the Poiesis API under Uvicorn.

One process and one event loop per Pod, building the app with
`poiesis.api.app:create_app`. Bind, port and drain time are intentionally
hardcoded: every Poiesis process in production runs behind a Kubernetes
Service on the same port, and scaling is done by adding Pod replicas, not
processes (asyncpg's pool isn't shared across processes). Kubernetes
restarts a process that dies.
"""

import uvicorn

from poiesis.core.logging_config import setup_logging

_HOST = "0.0.0.0"  # noqa: S104 - a container: the Service decides who reaches it
_PORT = 8000
#: Seconds running requests get to finish after SIGTERM. The chart's
#: termination grace period covers it (`api.terminationGracePeriodSeconds`).
_GRACEFUL_SHUTDOWN_SECONDS = 30


def run() -> None:
    """Serve the API until SIGTERM, then let running requests finish.

    Uvicorn's lines go through the Poiesis log setup. Its access log is
    off: the app writes its own (`poiesis.api.access_log`), which leaves
    out query strings. uvloop and httptools are used when installed.
    """
    setup_logging()
    uvicorn.run(
        "poiesis.api.app:create_app",
        factory=True,
        host=_HOST,
        port=_PORT,
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_SECONDS,
    )
