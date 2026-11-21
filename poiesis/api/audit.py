"""The audit log: one JSON object per line on stdout, per decision.

Every authorization outcome of a TES call (``task.create``,
``task.get``, ``task.list``, ``task.cancel``) and every API key event
(``apikey.mint``, ``apikey.revoke``, ``apikey.revoke_owner``,
``apikey.list_owner``) is written by the ``poiesis.audit`` logger as
one line of JSON, on a handler of its own (not propagated to the root
logger), so the format doesn't depend on the application's log setup
and a log pipeline can parse every line. Retention, shipping and
alerting are the operator's pipeline.

A line holds the time (``ts``, RFC 3339 UTC), the ``event``, its
``outcome`` (``allow``, ``deny`` or ``error``), the ``request_id`` and
who asked (``owner``, ``issuer``, ``via``, ``credential_id``,
``client``, ``actor``), plus event fields. It never holds tokens, keys,
key hashes or claim values: only identifiers.

The request id is the request's ``X-Request-ID`` (when it is a short,
printable value), else a new UUID; :class:`RequestIdMiddleware` keeps it
for the request and echoes it in the response's ``X-Request-ID``, so a
client can quote it.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from poiesis.api.auth import is_owner_id

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, MutableMapping

    from fastapi import Request

    from poiesis.api.auth import Principal

    # The ASGI types, spelled out (as in `starlette.types`).
    Message = MutableMapping[str, Any]
    Receive = Callable[[], Awaitable[Message]]
    Send = Callable[[Message], Awaitable[None]]
    ASGIApp = Callable[[Message, Receive, Send], Awaitable[None]]

logger = logging.getLogger("poiesis.audit")

#: Outcomes.
ALLOW = "allow"
DENY = "deny"
ERROR = "error"
#: Who decided: the built-in rules (claim rules, owner rule, built-in
#: admin, key scopes) or the decision service.
BUILTIN = "builtin"
DECISION_SERVICE = "decision_service"

_HEADER = b"x-request-id"
#: Client-sent request ids taken as they are: visible ASCII, no spaces,
#: short. Anything else is replaced, so a client can't flood or garble
#: log lines through it.
_CLIENT_REQUEST_ID = re.compile(r"[\x21-\x7e]{1,128}")
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "poiesis_request_id", default=None
)

#: Audit events by the operation id of their route. The owner-wide key
#: listing is an event; listing one's own keys is not.
_EVENTS = {
    "CreateTask": "task.create",
    "GetTask": "task.get",
    "ListTasks": "task.list",
    "CancelTask": "task.cancel",
    "CreateApiKey": "apikey.mint",
    "RevokeApiKey": "apikey.revoke",
    "RevokeApiKeys": "apikey.revoke_owner",
}


class _StdoutHandler(logging.Handler):
    """Writes each record's message as one line to the current stdout.

    Looked up on every record rather than bound once, so that whatever
    stdout is when a line is written (a test's capture included) gets it.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Write the message and a newline, and flush."""
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001 (logging must never raise)
            self.handleError(record)


def configure(*, enabled: bool) -> None:
    """Turn the audit log on or off; idempotent."""
    logger.propagate = False
    if not any(isinstance(h, _StdoutHandler) for h in logger.handlers):
        logger.addHandler(_StdoutHandler())
    logger.setLevel(logging.INFO if enabled else logging.CRITICAL + 1)


# On from import on, so that it never falls through to the app's handlers.
configure(enabled=True)


def request_id() -> str:
    """The current request's id; a new one outside a request."""
    return _request_id.get() or str(uuid.uuid4())


class RequestIdMiddleware:
    """Pure ASGI middleware: the request id, kept and echoed back.

    Pure ASGI rather than ``BaseHTTPMiddleware``, so that the context
    variable is set in the very task that runs the endpoint.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Message, receive: Receive, send: Send) -> None:
        """Set the request id for an HTTP request and add it to the response."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        sent = next(
            (
                value.decode("latin-1")
                for name, value in scope["headers"]
                if name.lower() == _HEADER
            ),
            "",
        )
        current = sent if _CLIENT_REQUEST_ID.fullmatch(sent) else str(uuid.uuid4())

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Replacing one the app may have set: there is one id.
                headers = [
                    (name, value)
                    for name, value in message.get("headers", ())
                    if name.lower() != _HEADER
                ]
                message["headers"] = [*headers, (_HEADER, current.encode())]
            await send(message)

        token = _request_id.set(current)
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _request_id.reset(token)


def emit(
    event: str, outcome: str, principal: Principal | None = None, **fields: Any
) -> None:
    """Write one audit line; fields that are ``None`` are left out.

    Callers pass identifiers only (ids, owners, counts, names of
    scopes), never secrets or claim values.
    """
    if not logger.isEnabledFor(logging.INFO):
        return
    line: dict[str, Any] = {
        "ts": datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "event": event,
        "outcome": outcome,
        "request_id": request_id(),
    }
    if principal is not None:
        actor = principal.actor
        client = principal.client
        line |= {
            "owner": principal.owner,
            "issuer": principal.issuer or None,
            "via": principal.via,
            "credential_id": principal.credential_id,
            # The client is the token's (unchecked) azp: a string or nothing.
            "client": client if isinstance(client, str) else None,
            "actor": actor and {"iss": actor.issuer, "sub": actor.subject},
        }
    line |= fields
    logger.info(
        "%s",
        json.dumps(
            {key: value for key, value in line.items() if value is not None},
            separators=(",", ":"),
            default=str,
        ),
    )


def denied(request: Request, principal: Principal) -> None:
    """Audit a request refused by a built-in check, if its route has an event.

    For the dependencies that refuse before the handler runs (claim
    rule, delegation, key scopes, key management); the task or key id
    and target owner come from the request, if well-formed.
    """
    route = request.scope.get("route")
    operation = getattr(route, "operation_id", None)
    owner = request.query_params.get("owner")
    if operation == "ListApiKeys" and owner is not None:
        event: str | None = "apikey.list_owner"
    else:
        event = _EVENTS.get(operation or "")
    if event is None:
        return
    fields: dict[str, Any] = {"decided_by": BUILTIN}
    path_id = _uuid(request.path_params.get("id"))
    if event.startswith("task."):
        fields |= {"admin": False, "task_id": path_id}
    elif event == "apikey.revoke":
        fields["key_id"] = path_id
    elif event.endswith("_owner") and owner is not None and is_owner_id(owner):
        fields["target_owner"] = owner
    emit(event, DENY, principal, **fields)


def _uuid(value: Any) -> str | None:
    """The canonical form of a UUID string, or ``None``."""
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError):
        return None
