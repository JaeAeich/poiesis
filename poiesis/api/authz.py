"""Authorization: per-issuer claim rules and an optional decision service.

Two independent parts, both off by default; when both are set, both
must allow:

- An issuer's claim rule (``requiredClaim``) admits a principal of that
    issuer (a token, or an API key minted with one) if one claim holds
    one of the configured values or starts with one of the configured
    prefixes. It never applies to another issuer's principals, so an
    issuer can't admit its tokens by copying another's claim values.
- The decision service is an OpenID AuthZEN 1.0 Access Evaluation
    endpoint (``POST`` ``/access/v1/evaluation``) that gets one question
    per decision, in the ``tes-authzen/2`` profile: the subject (owner id,
    ``iss``, ``sub``, ``client_id``, ``scope``, the authenticator ``via``
    and ``credential_id``, the ``actor`` of a delegated token and
    allowlisted claims; never the token), the TES ``operationId``
    as action, and a ``tes_task`` (get, cancel) or a ``tes_task_set``
    ``own``/``all`` (create, list) as resource. It answers a
    :class:`Decision`: a boolean, optionally refined under
    ``context.tes`` (a list ``scope``, the ``groups`` of a new task,
    ``obligations``, ``advice``, a ``reason``). Without it, the built-in
    owner rule applies: callers see and cancel only their own tasks, and
    delegated tokens (with an RFC 8693 ``act`` claim) are refused unless
    the actor is in the token issuer's ``actors``.

Tasks are visible to their owner only unless the operator turns
``sharing`` on: only then may the decision service show a caller other
owners' tasks (``all``, a ``scope``, a foreign ``GetTask``) or share a
new task with ``groups``. With it off, foreign and missing tasks are
``404`` without asking.

Any failure of the decision service, or a malformed answer, denies with
``503``; an obligation (Poiesis knows none) turns an allow into a deny.
There is no decision cache: a key would have to cover everything the
decision service sees, so caching belongs next to it (e.g. a sidecar).

Note: no ``from __future__ import annotations``; FastAPI introspects the
dependencies below at runtime (see `poiesis.api.auth`).
"""

import asyncio
import ipaddress
import logging
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, Request

from poiesis.api.apikey_auth import TASKS_READ, TASKS_WRITE
from poiesis.api.auth import Principal, get_principal
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import (
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from poiesis.api.settings import AuthzSettings, IssuerSettings
from poiesis.api.tes.models import TesInput, TesOutput, TesTask
from poiesis.db.tasks import TaskScope

logger = logging.getLogger(__name__)

PROFILE = "tes-authzen/2"
#: The scope dimensions; any other key makes the answer malformed, since
#: ignoring a dimension (all must match) would widen the scope.
_SCOPE_DIMENSIONS = frozenset({"owners", "groups", "tags"})
#: A leading RFC 3986 scheme and ``://`` (ASCII only, unlike ``\w``).
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


@dataclass(frozen=True)
class Decision:
    """One answer of the decision service, in the ``tes-authzen/2`` profile.

    ``allow`` is the decision after obligations. ``scope`` (only used
    for ``ListTasks`` on ``own``, with sharing on) adds other owners'
    tasks to the caller's; ``None`` adds none. ``groups`` (only used
    for ``CreateTask``, with sharing on) are the groups to share the new
    task with. ``obligations`` are what the service requires Poiesis to
    do; Poiesis knows none, so any of them denies. ``reason`` is for the
    log, never for the client. ``advice`` is accepted and ignored.
    """

    allow: bool
    scope: TaskScope | None = None
    groups: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()
    reason: str | None = None


def parse_decision(answer: Any) -> Decision:
    """Parse an AuthZEN response body; raise ``ValueError`` if malformed.

    ``decision`` must be a boolean. ``context.tes`` and each of its
    fields are optional, but present ones must have their types (``null``
    is not absent): ``scope`` an object with ``owners`` and ``groups``
    (lists of strings) and ``tags`` (an object of lists of strings),
    ``groups``, ``obligations`` and ``advice`` lists of strings,
    ``reason`` a string. Other keys of ``context`` and ``context.tes``
    are ignored, unknown scope dimensions are not.
    """
    if not isinstance(answer, dict):
        raise ValueError("the response is not an object")  # noqa: TRY004
    allow = answer.get("decision")
    if not isinstance(allow, bool):
        raise ValueError("decision is missing or not a boolean")  # noqa: TRY004
    context = _object(answer, "context", "context")
    tes = _object(context, "tes", "context.tes")
    reason = tes.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("context.tes.reason is not a string")
    _strings(tes, "advice", "context.tes.advice")
    return Decision(
        allow=allow,
        scope=_scope(tes),
        groups=_strings(tes, "groups", "context.tes.groups") or (),
        obligations=_strings(tes, "obligations", "context.tes.obligations") or (),
        reason=reason,
    )


def _object(parent: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    """Return ``parent[key]`` (an object), or ``{}`` if it is absent."""
    if key not in parent:
        return {}
    value = parent[key]
    if not isinstance(value, dict):
        raise ValueError(f"{where} is not an object")  # noqa: TRY004
    return value


def _strings(parent: Mapping[str, Any], key: str, where: str) -> tuple[str, ...] | None:
    """Return ``parent[key]`` (a list of strings) without duplicates, or ``None``."""
    if key not in parent:
        return None
    value = parent[key]
    if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
        raise ValueError(f"{where} is not a list of strings")
    strings: list[str] = value
    return tuple(dict.fromkeys(strings))


def _scope(tes: Mapping[str, Any]) -> TaskScope | None:
    """Parse ``context.tes.scope``; ``None`` if it adds no tasks.

    An absent or empty scope adds none, and so does one with an empty
    dimension: all dimensions must match, and an empty one matches nothing.
    """
    scope = _object(tes, "scope", "context.tes.scope")
    unknown = scope.keys() - _SCOPE_DIMENSIONS
    if unknown:
        raise ValueError(f"context.tes.scope has unknown dimensions {sorted(unknown)}")
    tags = None
    if "tags" in scope:
        pairs = _object(scope, "tags", "context.tes.scope.tags")
        tags = tuple(
            (key, value)
            for key in pairs
            for value in _strings(pairs, key, "context.tes.scope.tags values") or ()
        )
    dimensions = (
        _strings(scope, "owners", "context.tes.scope.owners"),
        _strings(scope, "groups", "context.tes.scope.groups"),
        tags,
    )
    present = [dimension for dimension in dimensions if dimension is not None]
    if not present or not all(present):
        return None
    return TaskScope(*dimensions)


class Authz:
    """The issuers' claim rules and, if configured, the decision service."""

    def __init__(
        self,
        settings: AuthzSettings,
        issuers: Sequence[IssuerSettings] = (),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Read the settings; open a client if a decision service is set."""
        # By issuer, not by namespace: issuers sharing a namespace may
        # still admit differently.
        self._rules = {
            entry.issuer: entry.required_claim
            for entry in issuers
            if entry.required_claim is not None
        }
        self._url = settings.decision_service_url
        self._timeout = settings.decision_service_timeout
        self._allowlist = settings.decision_service_claims
        self._sharing = settings.sharing
        self._max_owners = settings.max_owners
        self._headers: dict[str, str] = {}
        self._client: httpx.AsyncClient | None = None
        if not self._url:
            return
        _warn_if_plain_http(self._url)
        if settings.decision_service_credential_file:
            path = Path(settings.decision_service_credential_file)
            credential = path.read_text().strip()
            if not credential:
                raise ValueError(f"decision service credential file {path} is empty")
            self._headers["Authorization"] = "Bearer " + credential
        # asyncio.timeout in _ask bounds the whole call; this bounds each phase.
        # trust_env=False: proxy variables or ~/.netrc must not reroute
        # (or add credentials to) calls that carry the caller's claims.
        self._client = client or httpx.AsyncClient(
            timeout=self._timeout, trust_env=False
        )

    async def aclose(self) -> None:
        """Close the decision service client, if any."""
        if self._client is not None:
            await self._client.aclose()

    def gate(self, principal: Principal) -> None:
        """Apply the principal's issuer's claim rule and the delegation rule.

        Raises ``403`` unless the issuer of the principal has no claim
        rule or it admits, and for a delegated token (one with an actor)
        when there is no decision service, unless the actor is listed in
        the issuer's ``actors``: the built-in owner rule can't tell what
        any other actor may do.
        """
        actor = principal.actor
        if self._client is None and actor is not None and not actor.listed:
            raise ForbiddenError("delegated tokens (act claim) need a decision service")
        rule = self._rules.get(principal.issuer)
        if rule is None:
            return
        value = principal.claim(rule.name)
        values = [value] if isinstance(value, str) else value
        if not (
            isinstance(values, list)
            and all(isinstance(v, str) for v in values)
            and any(v in rule.values or v.startswith(rule.prefixes) for v in values)
        ):
            raise ForbiddenError("forbidden")

    async def check_create(
        self, principal: Principal, task: TesTask
    ) -> tuple[str, ...]:
        """Raise ``403`` unless creation is allowed; return the task's groups.

        The groups are the decision's ``groups`` with sharing on, else
        none; never the creator's groups claim, which may name whole
        communities.
        """
        if self._client is None:
            return ()
        resource = {
            "type": "tes_task_set",
            "id": "own",
            "properties": {"task": project(task)},
        }
        decision = await self._ask(principal, "CreateTask", resource)
        if not decision.allow:
            raise ForbiddenError("forbidden")
        return decision.groups if self._sharing else ()

    async def may_read(
        self,
        principal: Principal,
        task_id: str,
        meta: dict[str, Any] | None,
        view: str,
    ) -> bool:
        """Whether the caller may read the task.

        ``meta`` holds the task's ``owner``, ``state``, ``tags`` and
        ``groups``, or is ``None`` for a missing task. With sharing on,
        the decision service is asked even for missing tasks, which keeps
        missing and foreign tasks indistinguishable (both 404, both 503
        while it is down); with sharing off, it is asked about the
        caller's own tasks only, and both are 404 without a call.
        """
        own = _owns(principal, meta)
        if self._client is None or not (self._sharing or own):
            return own
        resource = _task_resource(task_id, meta)
        decision = await self._ask(principal, "GetTask", resource, {"view": view})
        return decision.allow

    async def check_cancel(
        self, principal: Principal, task_id: str, meta: dict[str, Any] | None
    ) -> None:
        """Raise ``404`` or ``403`` unless the caller may cancel the task.

        A denied caller who may read the task gets ``403``, anyone else
        ``404``. ``GetTask`` is asked after a denied cancel and always for
        a missing task, so a missing task never costs fewer calls than an
        existing one (one call for an allowed cancel of an existing task,
        two otherwise). With sharing off, foreign and missing tasks are
        ``404`` without a call, as in :meth:`may_read`.
        """
        own = _owns(principal, meta)
        if self._client is None or not (self._sharing or own):
            allowed, readable = own, False
        else:
            resource = _task_resource(task_id, meta)
            allowed = (await self._ask(principal, "CancelTask", resource)).allow
            readable = (not allowed or meta is None) and (
                await self._ask(principal, "GetTask", resource)
            ).allow
        if meta is not None and allowed:
            return
        if meta is not None and readable:
            raise ForbiddenError("forbidden")
        raise NotFoundError(f"task {task_id} not found")

    async def visible_tasks(
        self, principal: Principal, view: str
    ) -> tuple[str | None, TaskScope | None]:
        """Return the ``owner`` and ``scope`` to list by; raise ``403`` if denied.

        ``(None, None)`` lists every task, ``(owner, None)`` the caller's,
        ``(owner, scope)`` the caller's and those of the scope. With
        sharing off, only ``own`` is asked and its scope is ignored. With
        sharing on, ``all`` and ``own`` are asked in parallel; ``all``
        allowed lists every task, else ``own`` allowed lists the caller's
        and its scope's. A scope naming more than ``max_owners`` owners
        denies.
        """
        if self._client is None:
            return principal.owner, None
        if not self._sharing:
            if not (await self._ask_list(principal, "own", view)).allow:
                raise ForbiddenError("forbidden")
            return principal.owner, None
        every, own = await asyncio.gather(
            self._ask_list(principal, "all", view),
            self._ask_list(principal, "own", view),
        )
        if every.allow:
            return None, None
        if not own.allow:
            raise ForbiddenError("forbidden")
        scope = own.scope
        if scope is not None and len(scope.owners or ()) > self._max_owners:
            logger.error(
                "Decision service scope for ListTasks names %d owners, more than "
                "authz.maxOwners (%d); denied",
                len(scope.owners or ()),
                self._max_owners,
            )
            raise ForbiddenError("forbidden")
        return principal.owner, scope

    async def _ask_list(
        self, principal: Principal, task_set: str, view: str
    ) -> Decision:
        """Ask ``ListTasks`` on the task set ``all`` or ``own``."""
        resource = {"type": "tes_task_set", "id": task_set}
        return await self._ask(principal, "ListTasks", resource, {"view": view})

    def _subject(self, principal: Principal) -> dict[str, Any]:
        """Return the AuthZEN subject: validated identity, never the token."""
        token = principal.claims
        properties = {
            key: value
            for key, value in (
                ("iss", principal.issuer),
                ("sub", token.get("sub")),
                ("client_id", principal.client),
                ("via", principal.via),
                ("credential_id", principal.credential_id),
            )
            if value is not None
        }
        scope = token.get("scope", token.get("scp"))
        if principal.via == "apikey":
            # The key's own scopes, not those of the token that minted it.
            scope = sorted(principal.scopes)
            if principal.credential_issued_at is not None:
                # Seconds since minting; the claims snapshot is as old, so
                # a policy can refuse keys or claims older than it likes.
                age = max(0, int(time.time() - principal.credential_issued_at))
                properties["key_age"] = age
                properties["snapshot_age"] = age
        if isinstance(scope, str):
            scope = scope.split()
        if isinstance(scope, list):
            properties["scope"] = scope
        if principal.actor is not None:
            properties["actor"] = {
                "iss": principal.actor.issuer,
                "sub": principal.actor.subject,
            }
        properties["claims"] = {
            name: value
            for name in self._allowlist
            if (value := principal.claim(name)) is not None
        }
        return {"type": "user", "id": principal.owner, "properties": properties}

    async def _ask(
        self,
        principal: Principal,
        action: str,
        resource: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> Decision:
        """Ask the decision service once; any failure raises ``503``.

        A malformed answer is a failure too. An allow with obligations is
        turned into a deny: Poiesis knows none, so it can't fulfil them.
        """
        assert self._client is not None
        request_id = str(uuid.uuid4())
        body = {
            "subject": self._subject(principal),
            "action": {"name": action, "properties": properties or {}},
            "resource": resource,
            "context": {
                "tes": {
                    "profile": PROFILE,
                    "service_id": get_poiesis_api_constants().SERVICE_ID,
                }
            },
        }
        decision: Decision | None = None
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._client.post(
                    self._url,
                    json=body,
                    headers=self._headers | {"X-Request-ID": request_id},
                )
            cause = f"status {response.status_code}"
            if response.status_code == httpx.codes.OK:
                decision = parse_decision(response.json())
        except (httpx.HTTPError, TimeoutError) as exc:
            cause = type(exc).__name__
        except ValueError as exc:
            # Not JSON (JSONDecodeError is a ValueError), or malformed.
            cause = f"invalid response: {exc}"
        if decision is None:
            logger.error(
                "Decision service failed (%s) for %s on %s %s, request %s",
                cause,
                action,
                resource["type"],
                resource["id"],
                request_id,
            )
            raise ServiceUnavailableError(
                "authorization service unavailable", retry_after_seconds=1
            )
        if decision.allow and decision.obligations:
            logger.warning(
                "Decision service sent unknown obligations %s for %s on %s %s, "
                "request %s; denied",
                list(decision.obligations),
                action,
                resource["type"],
                resource["id"],
                request_id,
            )
            decision = replace(decision, allow=False)
        logger.info(
            "Decision %s for %s on %s %s, request %s, reason %r",
            decision.allow,
            action,
            resource["type"],
            resource["id"],
            request_id,
            decision.reason,
        )
        return decision


def get_authz(request: Request) -> Authz:
    """FastAPI dependency: the app's :class:`Authz`."""
    return request.app.state.authz


async def authorized_principal(
    principal: Annotated[Principal, Depends(get_principal)],
    authz: Annotated[Authz, Depends(get_authz)],
) -> Principal:
    """FastAPI dependency: the principal, admitted by the claim rule."""
    authz.gate(principal)
    return principal


def require_scope(principal: Principal, scope: str) -> None:
    """Raise ``403`` if an API key principal lacks ``scope``.

    Only API keys are limited by their scopes (``tasks:write`` implies
    ``tasks:read``); a token's scopes are the issuer's business
    (``requiredScopes``) and don't restrict TES operations.
    """
    if principal.via != "apikey":
        return
    granted = principal.scopes
    if scope in granted or (scope == TASKS_READ and TASKS_WRITE in granted):
        return
    raise ForbiddenError(f"API key lacks scope {scope}")


async def task_reader(
    principal: Annotated[Principal, Depends(authorized_principal)],
) -> Principal:
    """FastAPI dependency: an admitted principal that may read tasks."""
    require_scope(principal, TASKS_READ)
    return principal


async def task_writer(
    principal: Annotated[Principal, Depends(authorized_principal)],
) -> Principal:
    """FastAPI dependency: an admitted principal that may create or cancel."""
    require_scope(principal, TASKS_WRITE)
    return principal


def strip_url(url: str) -> str | None:
    """Remove credentials from a URL, or return ``None`` to omit it.

    The profile's plain string algorithm (URL parsers differ between
    languages, and falling back to the raw value would leak):

    0. A value with a tab, LF or CR anywhere is omitted (WHATWG-style
        clients delete them, so they can hide a host or an empty one).
    1. Only a leading RFC 3986 scheme followed by ``://`` counts; W is
        what follows, up to the first ``/`` or the end.
    2. If W's last ``@`` comes after its first ``?`` or ``#``, the
        value is ambiguous and omitted. So is a W with a backslash,
        which WHATWG-style clients read as ``/`` (another host).
    3. The authority (W up to its first ``?`` or ``#``) loses everything
        up to and including its last ``@``.
    4. The rest is cut at its first ``?`` or ``#``. If the authority is
        now empty and the rest has an ``@``, the value is omitted
        (WHATWG skips the extra slashes, so ``https:///u:p@h/p`` sends
        ``u:p`` to ``h``; this also covers an authority that held only
        userinfo, such as ``https://x@/u:p@h/p``).
    5. Without a scheme, the value is kept only if it has neither ``@``
        nor ``?``.
    6. Nothing else changes.
    """
    if any(character in url for character in "\t\n\r"):
        return None
    scheme = _SCHEME.match(url)
    if scheme is None:
        return None if "@" in url or "?" in url else url
    start = scheme.end()
    slash = url.find("/", start)
    end = len(url) if slash < 0 else slash
    cut = _first_of(url, "?#", start, end)
    if url.rfind("@", start, end) > cut or "\\" in url[start:end]:
        return None
    host = url[start:cut].rpartition("@")[2]
    rest = url[cut:]
    rest = rest[: _first_of(rest, "?#", 0, len(rest))]
    if not host and "@" in rest:
        return None
    return scheme.group() + host + rest


def _first_of(text: str, characters: str, start: int, end: int) -> int:
    """Return the index of the first of `characters` in a slice, or `end`."""
    found = (text.find(character, start, end) for character in characters)
    return min((index for index in found if index >= 0), default=end)


def project(task: TesTask) -> dict[str, Any]:
    """Return the fixed projection of a submitted task for ``CreateTask``.

    Leaves out what may hold secrets: commands, environments, input
    contents, ``backend_parameters`` and URL credentials.
    """
    resources = task.resources
    return _without_none(
        {
            "name": task.name,
            "tags": task.tags,
            "resources": resources
            and _without_none(
                {
                    "cpu_cores": resources.cpu_cores,
                    "ram_gb": resources.ram_gb,
                    "disk_gb": resources.disk_gb,
                    "preemptible": resources.preemptible,
                    "zones": resources.zones,
                }
            ),
            "volumes": task.volumes,
            "executors": [{"image": executor.image} for executor in task.executors],
            "inputs": task.inputs and [_file(i) for i in task.inputs],
            "outputs": task.outputs and [_file(o) for o in task.outputs],
        }
    )


def _file(item: TesInput | TesOutput) -> dict[str, Any]:
    """Project an input or output: ``url`` (stripped), ``path``, ``type``."""
    return _without_none(
        {
            "url": strip_url(item.url) if item.url else None,
            "path": item.path,
            "type": item.type.value if item.type else None,
        }
    )


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    """Drop the keys whose value is ``None``."""
    return {key: value for key, value in values.items() if value is not None}


def _owns(principal: Principal, meta: dict[str, Any] | None) -> bool:
    """Whether the task exists and is the principal's."""
    return meta is not None and meta["owner"] == principal.owner


def _task_resource(task_id: str, meta: dict[str, Any] | None) -> dict[str, Any]:
    """Return a ``tes_task``; no properties if the task is missing."""
    return {"type": "tes_task", "id": task_id, "properties": dict(meta or {})}


def _warn_if_plain_http(url: str) -> None:
    """Warn on plain HTTP to a host other than loopback.

    The connection to the decision service must be secured (AuthZEN
    1.0, section 11.1), typically by a service mesh, so plain HTTP is
    only a warning.
    """
    parsed = httpx.URL(url)
    try:
        loopback = ipaddress.ip_address(parsed.host).is_loopback
    except ValueError:
        loopback = parsed.host == "localhost"
    if parsed.scheme == "http" and not loopback:
        logger.warning(
            "The decision service URL uses plain http to a non-loopback "
            "host; secure the connection, e.g. with mesh mTLS"
        )
