"""Which `file://` URLs a task may use.

A `file://` URL is resolved inside the TIF/TOF container. That container
holds the service's own credentials, so the scheme is off unless the
operator names the directories it may reach (``taskpods.fileUrlRoots``,
usually paths mounted through ``taskpods.extraVolumeMounts``).
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

from poiesis.core.constants import FILE_URL_ROOTS_ENV


def parse_file_url_roots(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated list of absolute directories.

    Raises ``ValueError`` for a relative path or the filesystem root, which
    would expose the whole container.
    """
    roots: list[str] = []
    for item in (raw or "").split(","):
        entry = item.strip()
        if not entry:
            continue
        if not entry.startswith("/"):
            raise ValueError(f"{FILE_URL_ROOTS_ENV}: {entry!r} is not an absolute path")
        root = os.path.normpath(entry)
        if root == "/":
            raise ValueError(f"{FILE_URL_ROOTS_ENV}: '/' is not allowed as a root")
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def file_url_roots() -> tuple[str, ...]:
    """The roots configured for this process; empty when the scheme is off."""
    return parse_file_url_roots(os.environ.get(FILE_URL_ROOTS_ENV))


def _under(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in roots)


def file_url_path(uri: str) -> str:
    """The local path a `file://` URL names, normalised."""
    return os.path.normpath(unquote(urlparse(uri).path) or "/")


def file_url_allowed(uri: str) -> bool:
    """True if `uri` names a path under a configured root.

    A check on the URL text alone, for the API. TIF/TOF also call
    `resolve_file_url`, which follows symlinks.
    """
    parsed = urlparse(uri)
    if parsed.netloc not in ("", "localhost"):
        return False
    return _under(file_url_path(uri), file_url_roots())


def resolve_file_url(uri: str) -> str:
    """Return the real path for `uri`, or raise if it leaves the roots.

    Symlinks are resolved first, so a link under a root can't lead to
    another part of the container.
    """
    roots = tuple(os.path.realpath(root) for root in file_url_roots())
    if not roots or not file_url_allowed(uri):
        raise PermissionError(
            f"file:// URL is outside the directories this deployment allows: {uri}"
        )
    real = os.path.realpath(file_url_path(uri))
    if not _under(real, roots):
        raise PermissionError(
            f"file:// URL resolves outside the directories this deployment allows: "
            f"{uri}"
        )
    return real
