"""The API access log: one line per HTTP request.

Written by the ``poiesis.access`` logger through the application's log
setup, so it carries the request id like every other line. A line holds
the ``method``, the ``path`` (no query string), the response ``status``,
the ``duration_ms`` and, when the request was authenticated, the
``owner``. Headers, query strings and bodies are never logged.

Probe requests (``/healthz``, ``/readyz``, ``/startupz``) are logged at
DEBUG, so kubelet's polling doesn't flood the log at the default level.
"""

from __future__ import annotations

import contextvars
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, MutableMapping

    Message = MutableMapping[str, Any]
    Receive = Callable[[], Awaitable[Message]]
    Send = Callable[[Message], Awaitable[None]]
    ASGIApp = Callable[[Message, Receive, Send], Awaitable[None]]

logger = logging.getLogger("poiesis.access")

#: Paths of the Kubernetes probes (`poiesis.api.routes.health`).
PROBE_PATHS = frozenset({"/healthz", "/readyz", "/startupz"})

#: The current request's line fields that are learnt while serving it. A
#: dict set by the middleware, so a write from a copied context reaches it.
_noted: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "poiesis_access_noted", default=None
)


def note_owner(owner: str) -> None:
    """Record the authenticated owner for the current request's line."""
    noted = _noted.get()
    if noted is not None:
        noted["owner"] = owner


class AccessLogMiddleware:
    """Pure ASGI middleware: logs each request once it has been answered.

    Added inside :class:`poiesis.api.audit.RequestIdMiddleware`, so that
    the request id is set when the line is written.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Message, receive: Receive, send: Send) -> None:
        """Serve the request, then log its line."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500
        noted: dict[str, Any] = {}
        token = _noted.set(noted)

        async def send_and_note(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_note)
        finally:
            _noted.reset(token)
            path = scope.get("path", "")
            fields: dict[str, Any] = {
                "method": scope.get("method"),
                "path": path,
                "status": status,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            } | noted
            logger.log(
                logging.DEBUG if path in PROBE_PATHS else logging.INFO,
                "%s %s %s",
                fields["method"],
                path,
                status,
                extra=fields,
            )
