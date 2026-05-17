"""Filer strategy factory — dispatches by URI scheme and direction.

Two entry points, one per direction. Each looks up the registered
strategy class for the URI scheme and refuses combinations the strategy
cannot satisfy (e.g. `http://` outputs, `s3://` content uploads). The
refusal is a `ValueError` that flows out to a 400 at the API edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from poiesis.core.services.filer.strategy.content_filer import ContentFilerStrategy
from poiesis.core.services.filer.strategy.http_filer import HttpFilerStrategy
from poiesis.core.services.filer.strategy.local_filer import LocalFilerStrategy
from poiesis.core.services.filer.strategy.s3_filer import S3FilerStrategy

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
#: Every other entry maps to a real URI scheme.
_SCHEMES: dict[str, _SchemeEntry] = {
    "": _SchemeEntry(name="content", input=ContentFilerStrategy, output=None),
    "file": _SchemeEntry(
        name="file", input=LocalFilerStrategy, output=LocalFilerStrategy
    ),
    "s3": _SchemeEntry(name="s3", input=S3FilerStrategy, output=S3FilerStrategy),
    "http": _SchemeEntry(name="http", input=HttpFilerStrategy, output=None),
    "https": _SchemeEntry(name="https", input=HttpFilerStrategy, output=None),
}


def supported_input_schemes() -> list[str]:
    """Return the URI scheme names that can stage TES inputs."""
    return [e.name for e in _SCHEMES.values() if e.input is not None]


def supported_output_schemes() -> list[str]:
    """Return the URI scheme names that can upload TES outputs."""
    return [e.name for e in _SCHEMES.values() if e.output is not None]


def can_input(uri: str | None) -> bool:
    """True if `uri`'s scheme can be used as a TES input."""
    entry = _SCHEMES.get(_scheme(uri))
    return entry is not None and entry.input is not None


def can_output(uri: str | None) -> bool:
    """True if `uri`'s scheme can be used as a TES output."""
    entry = _SCHEMES.get(_scheme(uri))
    return entry is not None and entry.output is not None


def create_input_strategy(uri: str | None, payload: TesInput) -> InputFilerStrategy:
    """Construct an input strategy for `uri`, or raise `ValueError`."""
    entry = _SCHEMES.get(_scheme(uri))
    if entry is None:
        raise ValueError(f"Unsupported URI scheme: {uri!r}")
    if entry.input is None:
        raise ValueError(f"Scheme '{entry.name}' is not supported for TES inputs")
    return entry.input(payload)


def create_output_strategy(uri: str, payload: TesOutput) -> OutputFilerStrategy:
    """Construct an output strategy for `uri`, or raise `ValueError`."""
    entry = _SCHEMES.get(_scheme(uri))
    if entry is None:
        raise ValueError(f"Unsupported URI scheme: {uri!r}")
    if entry.output is None:
        raise ValueError(f"Scheme '{entry.name}' is not supported for TES outputs")
    return entry.output(payload)


def _scheme(uri: str | None) -> str:
    """Lowercase URI scheme; empty string for inline content (no URL)."""
    if not uri:
        return ""
    return urlparse(uri).scheme.lower()
