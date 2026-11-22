"""The API's Prometheus metrics.

HTTP requests are counted and timed by :class:`MetricsMiddleware`, labelled
by method, route template (``/ga4gh/tes/v1/tasks/{id}``, never the raw path)
and status. Task submissions are counted by outcome, and the database pool
is read at scrape time. The endpoint itself is served on its own port by
`poiesis.core.metrics.serve`, not by the FastAPI app.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from prometheus_client import Counter, Gauge, Histogram

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, MutableMapping

    from poiesis.db.pool import Pool

    Message = MutableMapping[str, Any]
    Receive = Callable[[], Awaitable[Message]]
    Send = Callable[[Message], Awaitable[None]]
    ASGIApp = Callable[[Message, Receive, Send], Awaitable[None]]

#: The ``route`` label of a request that matched no route.
UNMATCHED_ROUTE = "unmatched"

#: Methods kept as ``method`` label values; any other is ``other``.
_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

HTTP_REQUESTS = Counter(
    "poiesis_http_requests",
    "HTTP requests answered by the API.",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "poiesis_http_request_duration_seconds",
    "Time the API took to answer an HTTP request.",
    ["method", "route", "status"],
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "poiesis_http_requests_in_progress",
    "HTTP requests the API is serving now.",
)


class SubmitOutcome(StrEnum):
    """How a CreateTask request ended."""

    #: Persisted and its TaskPod submitted.
    CREATED = "created"
    #: Refused with a 400 before anything was written.
    REJECTED = "rejected"
    #: Persisted, but Kubernetes refused or didn't answer the submit.
    SUBMIT_FAILED = "submit_failed"


TASK_SUBMISSIONS = Counter(
    "poiesis_task_submissions",
    "CreateTask requests, by outcome.",
    ["outcome"],
)
for _outcome in SubmitOutcome:
    TASK_SUBMISSIONS.labels(outcome=_outcome.value)

DB_POOL_SIZE = Gauge(
    "poiesis_db_pool_size", "Connections the API's database pool has open."
)
DB_POOL_MAX_SIZE = Gauge(
    "poiesis_db_pool_max_size", "Connections the API's database pool may open."
)
DB_POOL_IN_USE = Gauge(
    "poiesis_db_pool_in_use", "Connections of the API's database pool in use."
)
DB_POOL_WAITERS = Gauge(
    "poiesis_db_pool_waiters",
    "Requests waiting for a connection of the API's database pool.",
)


def count_submission(outcome: SubmitOutcome) -> None:
    """Count one CreateTask request that ended with ``outcome``."""
    TASK_SUBMISSIONS.labels(outcome=outcome.value).inc()


def observe_pool(pool: Pool | None) -> None:
    """Read the pool gauges from ``pool`` at scrape time; 0 without a pool."""

    def read(stat: Callable[[Pool], int]) -> Callable[[], float]:
        return lambda: float(stat(pool)) if pool is not None else 0.0

    DB_POOL_SIZE.set_function(read(lambda p: p.size()))
    DB_POOL_MAX_SIZE.set_function(read(lambda p: p.max_size()))
    DB_POOL_IN_USE.set_function(read(lambda p: p.in_use()))
    DB_POOL_WAITERS.set_function(read(lambda p: p.waiters()))


def route_template(scope: Message) -> str:
    """The path template of the route that served ``scope``.

    Set by the router on the scope once a route matched; a request that
    matched none gets `UNMATCHED_ROUTE`, so a raw path never becomes a label.
    """
    path = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) else UNMATCHED_ROUTE


class MetricsMiddleware:
    """Pure ASGI middleware: counts and times each HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Message, receive: Receive, send: Send) -> None:
        """Serve the request, then record it."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def send_and_note(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        HTTP_REQUESTS_IN_PROGRESS.inc()
        try:
            await self.app(scope, receive, send_and_note)
        finally:
            HTTP_REQUESTS_IN_PROGRESS.dec()
            method = scope.get("method", "")
            labels = {
                "method": method if method in _METHODS else "other",
                "route": route_template(scope),
                "status": str(status),
            }
            HTTP_REQUESTS.labels(**labels).inc()
            HTTP_REQUEST_DURATION.labels(**labels).observe(time.perf_counter() - start)
