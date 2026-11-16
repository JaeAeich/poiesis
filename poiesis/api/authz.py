"""Authorization: a built-in claim rule and an optional decision service.

Two independent parts, both off by default; when both are set, both
must allow:

- The claim rule admits a caller if one claim holds one of the
  configured values or starts with one of the configured prefixes.
- The decision service is an OpenID AuthZEN 1.0 Access Evaluation
  endpoint (``POST`` ``/access/v1/evaluation``) that gets one question
  per decision, in the ``tes-authzen/1`` profile: the subject (owner id,
  ``iss``, ``sub``, ``client_id``, ``scope`` and allowlisted claims; never
  the token), the TES ``operationId`` as action, and a ``tes_task`` (get,
  cancel) or a ``tes_task_set`` ``own``/``all`` (create, list) as
  resource. Without it, the built-in owner rule applies: callers see and
  cancel only their own tasks.

Any failure of the decision service denies with ``503``.

Note: no ``from __future__ import annotations``; FastAPI introspects the
dependencies below at runtime (see `poiesis.api.auth`).
"""

import asyncio
import ipaddress
import logging
import uuid
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, Request

from poiesis.api.auth import Principal, get_principal
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import (
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from poiesis.api.settings import AuthzSettings
from poiesis.api.tes.models import TesInput, TesOutput, TesTask

logger = logging.getLogger(__name__)

PROFILE = "tes-authzen/1"
#: Owner of tasks created before owners were stamped: nobody's.
_LEGACY_OWNER = "__legacy__"


class Authz:
    """The claim rule and, if configured, the decision service."""

    def __init__(
        self, settings: AuthzSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        """Read the settings; open a client if a decision service is set."""
        self._claim = settings.required_claim_name
        self._values = frozenset(settings.required_claim_values)
        self._prefixes = settings.required_claim_prefixes
        self._url = settings.decision_service_url
        self._timeout = settings.decision_service_timeout
        self._allowlist = settings.decision_service_claims
        self._headers: dict[str, str] = {}
        self._client: httpx.AsyncClient | None = None
        if not self._url:
            return
        _check_url(self._url)
        if settings.decision_service_credential_file:
            credential = Path(settings.decision_service_credential_file).read_text()
            self._headers["Authorization"] = "Bearer " + credential.strip()
        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    async def aclose(self) -> None:
        """Close the decision service client, if any."""
        if self._client is not None:
            await self._client.aclose()

    def gate(self, principal: Principal) -> None:
        """Apply the claim rule; raise ``403`` unless it is off or admits."""
        if not self._claim:
            return
        value = principal.claim(self._claim)
        values = [value] if isinstance(value, str) else value
        if not (
            isinstance(values, list)
            and all(isinstance(v, str) for v in values)
            and any(v in self._values or v.startswith(self._prefixes) for v in values)
        ):
            raise ForbiddenError("forbidden")

    async def check_create(self, principal: Principal, task: TesTask) -> None:
        """Raise ``403`` unless the decision service (if any) allows creation."""
        if self._client is None:
            return
        resource = {
            "type": "tes_task_set",
            "id": "own",
            "properties": {"task": project(task)},
        }
        if not await self._ask(principal, "CreateTask", resource):
            raise ForbiddenError("forbidden")

    async def may_read(
        self,
        principal: Principal,
        task_id: str,
        meta: dict[str, Any] | None,
        view: str,
    ) -> bool:
        """Whether the caller may read the task; asked even if it is missing.

        ``meta`` holds the task's ``owner``, ``state`` and ``tags``, or is
        ``None`` for a missing task. Asking for missing tasks too keeps
        missing and foreign tasks indistinguishable (both 404, both 503
        while the decision service is down).
        """
        if self._client is None:
            return meta is not None and meta["owner"] == principal.id
        resource = _task_resource(task_id, meta)
        return await self._ask(principal, "GetTask", resource, {"view": view})

    async def check_cancel(
        self, principal: Principal, task_id: str, meta: dict[str, Any] | None
    ) -> None:
        """Raise ``404`` or ``403`` unless the caller may cancel the task.

        A denied caller who may read the task gets ``403``, anyone else
        ``404``.
        """
        if self._client is None:
            allowed = meta is not None and meta["owner"] == principal.id
        else:
            resource = _task_resource(task_id, meta)
            allowed = await self._ask(principal, "CancelTask", resource)
        if meta is None:
            raise NotFoundError(f"task {task_id} not found")
        if allowed:
            return
        if self._client is not None and await self._ask(
            principal, "GetTask", _task_resource(task_id, meta)
        ):
            raise ForbiddenError("forbidden")
        raise NotFoundError(f"task {task_id} not found")

    async def lists_all(self, principal: Principal, view: str) -> bool:
        """Whether the caller lists all tasks (``True``) or only their own.

        Asks for the task sets ``all`` and ``own``; raises ``403`` if
        neither is allowed.
        """
        if self._client is None:
            return False
        list_all, list_own = await asyncio.gather(
            *(
                self._ask(
                    principal,
                    "ListTasks",
                    {"type": "tes_task_set", "id": task_set},
                    {"view": view},
                )
                for task_set in ("all", "own")
            )
        )
        if not (list_all or list_own):
            raise ForbiddenError("forbidden")
        return list_all

    def _subject(self, principal: Principal) -> dict[str, Any]:
        """Return the AuthZEN subject: validated identity, never the token."""
        token = principal.claims
        properties = {
            key: value
            for key, value in (
                ("iss", token.get("iss")),
                ("sub", token.get("sub")),
                ("client_id", token.get("azp") or token.get("client_id")),
            )
            if value is not None
        }
        scope = token.get("scope", token.get("scp"))
        if isinstance(scope, str):
            scope = scope.split()
        if isinstance(scope, list):
            properties["scope"] = scope
        properties["claims"] = {
            name: value
            for name in self._allowlist
            if (value := principal.claim(name)) is not None
        }
        return {"type": "user", "id": principal.id, "properties": properties}

    async def _ask(
        self,
        principal: Principal,
        action: str,
        resource: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """Ask the decision service once; any failure raises ``503``."""
        if self._client is None:
            raise RuntimeError("no decision service configured")
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
        answer: Any = None
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._client.post(
                    self._url,
                    json=body,
                    headers=self._headers | {"X-Request-ID": request_id},
                )
            cause = f"status {response.status_code}"
            if response.status_code == httpx.codes.OK:
                answer = response.json()
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            cause = type(exc).__name__
        decision = answer.get("decision") if isinstance(answer, dict) else None
        if not isinstance(decision, bool):
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
        logger.info(
            "Decision %s for %s on %s %s, request %s",
            decision,
            action,
            resource["type"],
            resource["id"],
            request_id,
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


def strip_url(url: str) -> str | None:
    """Remove credentials from a URL, or return ``None`` to omit it.

    A plain string algorithm (URL parsers differ between languages, and
    falling back to the raw value would leak): cut at the first ``?`` or
    ``#``; with ``://``, drop the authority up to its last ``@``; without
    ``://``, keep the value only if it has no ``@``. Nothing else changes.
    """
    for separator in "?#":
        url = url.split(separator, 1)[0]
    scheme_end = url.find("://")
    if scheme_end < 0:
        return None if "@" in url else url
    start = scheme_end + 3
    end = url.find("/", start)
    at = url.rfind("@", start, len(url) if end < 0 else end)
    return url if at < 0 else url[:start] + url[at + 1 :]


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


def _task_resource(task_id: str, meta: dict[str, Any] | None) -> dict[str, Any]:
    """Return a ``tes_task``; no properties if missing, no owner if legacy."""
    properties = dict(meta or {})
    if properties.get("owner") == _LEGACY_OWNER:
        del properties["owner"]
    return {"type": "tes_task", "id": task_id, "properties": properties}


def _check_url(url: str) -> None:
    """Refuse non-HTTP(S) URLs; warn on plain HTTP to another host.

    The connection to the decision service must be secured (AuthZEN
    1.0, section 11.1), typically by a service mesh, so plain HTTP is
    only a warning.
    """
    scheme, _, rest = url.partition("://")
    if scheme not in {"http", "https"} or not rest:
        raise ValueError("POIESIS_AUTHZ_DECISION_SERVICE_URL must be http(s)")
    host = httpx.URL(url).host
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if scheme == "http" and not loopback:
        logger.warning(
            "The decision service URL uses plain http to a non-loopback "
            "host; secure the connection, e.g. with mesh mTLS"
        )
