"""Filer strategy factory — dispatches by URI scheme and direction.

Two entry points, one per direction. Each looks up the registered
strategy class for the URI scheme and refuses combinations the strategy
cannot satisfy (e.g. inline content as an output). The refusal is a
`ValueError` that flows out to a 400 at the API edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from poiesis.core.services.filer.file_urls import file_url_allowed, file_url_roots
from poiesis.core.services.filer.strategy.content_filer import ContentFilerStrategy
from poiesis.core.services.filer.strategy.drs_filer import (
    DrsFilerStrategy,
    drs_enabled,
    drs_uri_problem,
)
from poiesis.core.services.filer.strategy.ftp_filer import (
    FtpFilerStrategy,
    ftp_enabled,
)
from poiesis.core.services.filer.strategy.http_filer import HttpFilerStrategy
from poiesis.core.services.filer.strategy.local_filer import LocalFilerStrategy
from poiesis.core.services.filer.strategy.object_store_filer import (
    ObjectStoreFilerStrategy,
)

if TYPE_CHECKING:
    from poiesis.api.tes.models import TesInput, TesOutput
    from poiesis.core.services.filer.strategy.filer_strategy import (
        InputFilerStrategy,
        OutputFilerStrategy,
    )


@dataclass(frozen=True)
class _SchemeEntry:
    """Registry entry: which adapter classes a URI scheme can produce."""

    name: str
    input: type[InputFilerStrategy] | None
    output: type[OutputFilerStrategy] | None


#: The empty-scheme entry is reserved for inline `TesInput.content`.
#: Every other entry maps to a real URI scheme. `drs` resolves to another
#: URL first; its strategy hands the resolved URL to the entry for its
#: scheme.
_SCHEMES: dict[str, _SchemeEntry] = {
    "": _SchemeEntry(name="content", input=ContentFilerStrategy, output=None),
    "file": _SchemeEntry(
        name="file", input=LocalFilerStrategy, output=LocalFilerStrategy
    ),
    # One strategy for every object store. Submit accepts a scheme only
    # when the operator enabled its provider (`RuntimeConfig.storage_enabled`).
    "s3": _SchemeEntry(
        name="s3", input=ObjectStoreFilerStrategy, output=ObjectStoreFilerStrategy
    ),
    "gs": _SchemeEntry(
        name="gs", input=ObjectStoreFilerStrategy, output=ObjectStoreFilerStrategy
    ),
    "az": _SchemeEntry(
        name="az", input=ObjectStoreFilerStrategy, output=ObjectStoreFilerStrategy
    ),
    "http": _SchemeEntry(
        name="http", input=HttpFilerStrategy, output=HttpFilerStrategy
    ),
    "https": _SchemeEntry(
        name="https", input=HttpFilerStrategy, output=HttpFilerStrategy
    ),
    # On unless the operator turns them off (`ftp_enabled`).
    "ftp": _SchemeEntry(name="ftp", input=FtpFilerStrategy, output=FtpFilerStrategy),
    "ftps": _SchemeEntry(name="ftps", input=FtpFilerStrategy, output=FtpFilerStrategy),
    # Off unless the operator turns it on (`drs_enabled`). Inputs only.
    "drs": _SchemeEntry(name="drs", input=DrsFilerStrategy, output=None),
}


def supported_input_schemes() -> list[str]:
    """Return the URI scheme names that can stage TES inputs."""
    return [e.name for e in _enabled() if e.input is not None]


def supported_output_schemes() -> list[str]:
    """Return the URI scheme names that can upload TES outputs."""
    return [e.name for e in _enabled() if e.output is not None]


def _enabled() -> list[_SchemeEntry]:
    """Registry entries usable in this deployment.

    `file` counts only when the operator configured roots for it, `ftp`
    and `ftps` unless the operator turned them off, `drs` only when the
    operator turned it on.
    """
    on = {"file": bool(file_url_roots()), "drs": drs_enabled()}
    on["ftp"] = on["ftps"] = ftp_enabled()
    return [e for e in _SCHEMES.values() if on.get(e.name, True)]


def refusal(uri: str | None) -> str | None:
    """Why this deployment refuses `uri` though its scheme is registered.

    None if it doesn't. For `ftp`/`ftps` turned off and for `drs` URIs;
    the submit check puts the reason in its 400.
    """
    name = scheme(uri)
    if name in {"ftp", "ftps"} and not ftp_enabled():
        return f"is an {name}:// URL, but this deployment has FTP turned off"
    if name == "drs":
        assert uri is not None
        return drs_uri_problem(uri)
    return None


def _lookup(uri: str | None) -> _SchemeEntry | None:
    """Registry entry for `uri`, or None if its scheme or path is refused."""
    entry = _SCHEMES.get(scheme(uri))
    if entry is not None and entry.name == "file":
        assert uri is not None
        if not file_url_allowed(uri):
            return None
    if entry is not None and refusal(uri):
        return None
    return entry


def can_input(uri: str | None) -> bool:
    """True if `uri` can be used as a TES input."""
    entry = _lookup(uri)
    return entry is not None and entry.input is not None


def can_output(uri: str | None) -> bool:
    """True if `uri` can be used as a TES output."""
    entry = _lookup(uri)
    return entry is not None and entry.output is not None


def input_url(tes_input: TesInput) -> str | None:
    """The URL `tes_input` is staged from; None stages its inline content.

    TES: "If content is not empty, "url" must be ignored."
    """
    return None if tes_input.content else tes_input.url


def create_input_strategy(uri: str | None, payload: TesInput) -> InputFilerStrategy:
    """Construct an input strategy for `uri`, or raise `ValueError`."""
    entry = _lookup(uri)
    if entry is None:
        raise ValueError(f"Unsupported URI: {uri!r}")
    if entry.input is None:
        raise ValueError(f"Scheme '{entry.name}' is not supported for TES inputs")
    return entry.input(payload)


def create_output_strategy(uri: str, payload: TesOutput) -> OutputFilerStrategy:
    """Construct an output strategy for `uri`, or raise `ValueError`."""
    entry = _lookup(uri)
    if entry is None:
        raise ValueError(f"Unsupported URI: {uri!r}")
    if entry.output is None:
        raise ValueError(f"Scheme '{entry.name}' is not supported for TES outputs")
    return entry.output(payload)


def scheme(uri: str | None) -> str:
    """Lowercase URI scheme; empty string for inline content (no URL)."""
    if not uri:
        return ""
    return urlparse(uri).scheme.lower()
