"""DRS filer strategy: `drs://` inputs, resolved to a URL another strategy stages.

A hostname-based DRS URI (GA4GH DRS 1.x), ``drs://<host>/<object_id>``,
names an object on the DRS server at ``https://<host>/ga4gh/drs/v1``. TIF
fetches the object, picks the first of its access methods whose URL this
deployment can stage (HTTPS first, then the object stores the operator
enabled, then FTP and HTTP), follows an ``access_id`` through
``/access/<access_id>``, and hands the URL to the strategy for its scheme.
An object-store URL counts only when one of the deployment's stores serves
its bucket (`object_store_filer.is_served`): the same lookup as for a
task's own URLs.
Headers the server returns with the URL go with the data request.

The scheme is off unless the operator turns it on (``taskpods.drs.enabled``),
optionally for a list of hosts only. A bearer token for DRS servers, from
an operator Secret, reaches TIF only and goes to the DRS server only, never
to the data URL.

Not supported: compact-identifier URIs (``drs://namespace:accession``),
which need a resolver, and bundles (objects with ``contents``).
"""

from __future__ import annotations

import logging
import os
from http import HTTPStatus
from typing import Any
from urllib.parse import quote, urlsplit

import requests

from poiesis.core.constants import (
    DRS_ALLOWED_HOSTS_ENV,
    DRS_BEARER_TOKEN_ENV,
    DRS_ENABLED_ENV,
    DRS_OBJECT_STORES_ENV,
)
from poiesis.core.filer.strategy.filer_strategy import (
    InputFilerStrategy,
    redact_url,
)
from poiesis.core.filer.strategy.ftp_filer import ftp_enabled
from poiesis.core.filer.strategy.http_filer import (
    _TRANSIENT_STATUSES,
    HttpFilerStrategy,
    _retry,
)
from poiesis.core.filer.strategy.object_store_filer import is_served
from poiesis.errors import PoiesisError
from poiesis.tes.models import TesInput

logger = logging.getLogger(__name__)

#: Base URL of the DRS API of a host. Tests point it at a local server.
_API_URL = "https://{host}/ga4gh/drs/v1"
_TIMEOUT_SECONDS = 30
#: URL schemes an access method may resolve to, most preferred first.
_PREFERENCE = ("https", "s3", "gs", "az", "ftps", "ftp", "http")
_OBJECT_STORES = frozenset({"s3", "gs", "az"})
_FTP = frozenset({"ftp", "ftps"})
_ON = frozenset({"1", "true", "yes", "on"})


class DrsError(PoiesisError):
    """A DRS object that can't be resolved to a URL this deployment can stage."""


def drs_enabled() -> bool:
    """True if the operator turned `drs://` inputs on (``taskpods.drs.enabled``)."""
    return os.environ.get(DRS_ENABLED_ENV, "").strip().lower() in _ON


def drs_allowed_hosts() -> tuple[str, ...]:
    """Hosts `drs://` URIs may name, lower case; empty allows any host."""
    raw = os.environ.get(DRS_ALLOWED_HOSTS_ENV, "")
    return tuple(h.strip().lower() for h in raw.split(",") if h.strip())


def parse_drs_uri(uri: str) -> tuple[str, str]:
    """`(host, object_id)` of a hostname-based DRS URI, or raise `ValueError`."""
    rest = uri.partition("://")[2]
    if ":" in rest:
        raise ValueError(
            "is a compact-identifier DRS URI (namespace:accession), which this "
            "deployment can't resolve; use drs://<host>/<object_id>"
        )
    host, _, object_id = rest.partition("/")
    if not host or not object_id or "/" in object_id or "?" in rest or "#" in rest:
        raise ValueError("is not a DRS URI of the form drs://<host>/<object_id>")
    return host.lower(), object_id


def drs_uri_problem(uri: str) -> str | None:
    """Why `uri` can't be used as a `drs://` input here, or None if it can."""
    if not drs_enabled():
        return "is a drs:// URI, but this deployment has DRS inputs turned off"
    try:
        host, _ = parse_drs_uri(uri)
    except ValueError as e:
        return str(e)
    allowed = drs_allowed_hosts()
    if allowed and host not in allowed:
        return f"names DRS host {host!r}, which this deployment doesn't allow"
    return None


def stageable_schemes() -> list[str]:
    """Schemes a DRS access URL may have here, most preferred first."""
    stores = {
        s.strip().lower()
        for s in os.environ.get(DRS_OBJECT_STORES_ENV, "").split(",")
        if s.strip()
    }
    ftp = ftp_enabled()
    return [
        s
        for s in _PREFERENCE
        if (s not in _OBJECT_STORES or s in stores) and (s not in _FTP or ftp)
    ]


class DrsFilerStrategy(InputFilerStrategy):
    """Input strategy for `drs://` URIs: resolve, then stage with another strategy."""

    def __init__(self, payload: TesInput) -> None:
        """Initialise with the TES input."""
        super().__init__(payload)
        assert isinstance(payload, TesInput)
        self.input = payload

    async def download_input_file(self, container_path: str) -> None:
        """Resolve the DRS object and stage the URL it resolves to."""
        assert self.input.url is not None
        url, headers = resolve(self.input.url)
        logger.info("Resolved %s to %s", self.input.url, redact_url(url))
        # Imported here: the factory imports this module.
        from poiesis.core.filer import filer_strategy_factory  # noqa: PLC0415

        resolved = self.input.model_copy(update={"url": url})
        strategy = filer_strategy_factory.create_input_strategy(url, resolved)
        if isinstance(strategy, HttpFilerStrategy):
            strategy.headers = headers
        await strategy.download_input_file(container_path)

    async def download_input_directory(self, container_path: str) -> None:
        """A DRS object is one file; refuse."""
        raise NotImplementedError("A DRS object can't be staged as a DIRECTORY")


def resolve(uri: str) -> tuple[str, dict[str, str]]:
    """The URL of the DRS object `uri` names, and the headers to fetch it with.

    Raises `DrsError` for a bundle, an object with no access method this
    deployment can stage, or a refusal by the DRS server.
    """
    problem = drs_uri_problem(uri)
    if problem:
        raise DrsError(f"{uri} {problem}")
    host, object_id = parse_drs_uri(uri)
    base = f"{_API_URL.format(host=host)}/objects/{quote(object_id, safe='')}"
    obj = _get_json(base, uri)
    if obj.get("contents"):
        raise DrsError(f"{uri} is a DRS bundle; only single objects can be staged")
    schemes = stageable_schemes()
    methods = [m for m in obj.get("access_methods") or [] if isinstance(m, dict)]
    ranked = sorted(
        (m for m in methods if _method_scheme(m) in schemes),
        key=lambda m: schemes.index(_method_scheme(m)),
    )
    for method in ranked:
        access_url = method.get("access_url")
        if isinstance(access_url, dict) and access_url.get("url"):
            answer = access_url
        elif method.get("access_id"):
            access_id = quote(str(method["access_id"]), safe="")
            answer = _get_json(f"{base}/access/{access_id}", uri)
        else:
            continue
        url = str(answer.get("url") or "")
        scheme = urlsplit(url).scheme.lower()
        headers = _headers(answer.get("headers"))
        if scheme not in schemes:
            continue
        if scheme in _OBJECT_STORES and not is_served(url):
            # A bucket none of this deployment's stores serves.
            continue
        if headers and scheme not in {"http", "https"}:
            # Headers can't go with an object-store or FTP transfer.
            continue
        return url, headers
    offered = sorted({str(m.get("type")) for m in methods})
    raise DrsError(
        f"{uri} has no access method this deployment can stage "
        f"(offered: {', '.join(offered) or 'none'}; "
        f"supported: {', '.join(schemes)})"
    )


def _method_scheme(method: dict[str, Any]) -> str:
    """The URL scheme an access method resolves to, as far as it says."""
    access_url = method.get("access_url")
    if isinstance(access_url, dict) and access_url.get("url"):
        return urlsplit(str(access_url["url"])).scheme.lower()
    return str(method.get("type") or "").lower()


def _headers(raw: object) -> dict[str, str]:
    """Headers of an access URL: ``["Name: value", ...]`` per DRS 1.x."""
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    headers: dict[str, str] = {}
    for item in raw if isinstance(raw, list) else []:
        name, sep, value = str(item).partition(":")
        if sep and name.strip():
            headers[name.strip()] = value.strip()
    return headers


def _get_json(url: str, uri: str) -> dict[str, Any]:
    """GET `url` from the DRS server with its bearer token, if any.

    Transient failures are retried as `http_filer` retries them.
    """
    token = os.environ.get(DRS_BEARER_TOKEN_ENV)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    result: dict[str, Any] = {}

    def once() -> None:
        response = requests.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
        status = response.status_code
        if status in _TRANSIENT_STATUSES:
            raise requests.HTTPError(
                f"DRS server answered {status} for {uri}", response=response
            )
        if status == HTTPStatus.NOT_FOUND:
            raise DrsError(f"DRS server has no object {uri} (404)")
        if status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            raise DrsError(f"DRS server refused access to {uri} ({status})")
        if not HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
            raise DrsError(f"DRS server answered {status} for {uri}")
        try:
            body = response.json()
        except ValueError:
            raise DrsError(f"DRS server sent no JSON for {uri}") from None
        if not isinstance(body, dict):
            raise DrsError(f"DRS server sent no JSON object for {uri}")
        result.update(body)

    _retry(once, f"DRS lookup of {uri}")
    return result
