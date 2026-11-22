"""FTP filer strategy: `ftp://` and `ftps://` inputs and outputs.

Uses the standard library's `ftplib`, in passive mode and binary. `ftps://`
is explicit TLS (``AUTH TLS``, then a protected data channel), with the
server's certificate checked. A URL with no user logs in as ``anonymous``,
as public archives (EBI, ENA, NCBI) expect; a URL with ``user:password@``
logs in with them. Those credentials are stored with the task; logs and
termination messages leave them out.

The URL's path is relative to the login directory, as in RFC 1738: for
public archives that is the server's root. A path that starts with
``%2F`` is absolute.

An input is written to a temporary file next to its path and renamed into
place once complete, as `http_filer` does. A transient failure (a dropped
connection, a timeout, a 4xx reply) is retried twice; a 5xx reply, such as
550 for a file that is missing or not readable, fails at once.
"""

from __future__ import annotations

import asyncio
import contextlib
import ftplib
import logging
import os
import posixpath
import socket
import ssl
import time
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.constants import FTP_ENABLED_ENV
from poiesis.core.services.filer.strategy.filer_strategy import (
    InputFilerStrategy,
    OutputFilerStrategy,
    redact_url,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)

_ATTEMPTS = 3
_TIMEOUT_SECONDS = 60
#: Deepest directory a DIRECTORY input walks into: a server whose listing
#: loops (a link to a parent) must not fill the task volume.
_MAX_DEPTH = 64
_OFF = frozenset({"0", "false", "no", "off"})


def ftp_enabled() -> bool:
    """True unless the operator turned FTP off (``taskpods.ftp.enabled``)."""
    return os.environ.get(FTP_ENABLED_ENV, "").strip().lower() not in _OFF


class FtpError(Exception):
    """The FTP server refused a login or a command for good (a 5xx reply)."""


class FtpFilerStrategy(InputFilerStrategy, OutputFilerStrategy):
    """Filer strategy for FTP and FTPS inputs and outputs."""

    def __init__(self, payload: TesInput | TesOutput) -> None:
        """Initialise with the TES input or output."""
        super().__init__(payload)
        self.input = self.payload if isinstance(self.payload, TesInput) else None
        self.output = self.payload if isinstance(self.payload, TesOutput) else None

    async def download_input_file(self, container_path: str) -> None:
        """Download the input file to `container_path`."""
        assert self.input is not None
        assert self.input.url is not None
        url = self.input.url

        def run(ftp: ftplib.FTP) -> None:
            _download_file(ftp, _remote_path(url), container_path)

        await asyncio.to_thread(_with_session, url, "download", run)
        logger.info("Downloaded %s to %s", redact_url(url), container_path)

    async def download_input_directory(self, container_path: str) -> None:
        """Download the input directory, and everything under it, to `container_path`.

        Each entry a listing names is staged under `container_path` by its
        last path segment; ``.`` and ``..`` are skipped.
        """
        assert self.input is not None
        assert self.input.url is not None
        url = self.input.url

        def run(ftp: ftplib.FTP) -> None:
            remote = _remote_path(url)
            if not _is_dir(ftp, remote):
                raise FtpError(f"{redact_url(url)} is not a directory on the server")
            _download_tree(ftp, remote, container_path, 0)

        await asyncio.to_thread(_with_session, url, "download", run)
        logger.info("Downloaded %s to %s", redact_url(url), container_path)

    async def upload_output_file(self, container_path: str) -> None:
        """Upload the file at `container_path` to the output URL."""
        assert self.output is not None
        url = self.output.url
        await self._upload([(container_path, url)])

    async def upload_output_directory(self, container_path: str) -> None:
        """Upload each file under `container_path` to the output URL plus its path."""
        assert self.output is not None
        if not os.path.isdir(container_path):
            raise FileNotFoundError(f"Output directory not found: {container_path}")
        await self._upload(_directory_files(container_path, self.output.url))

    async def upload_glob(self, glob_files: list[tuple[str, str, bool]]) -> None:
        """Upload each glob match to the output URL plus its relative path."""
        assert self.output is not None
        files: list[tuple[str, str]] = []
        for path, relative_path, is_directory in glob_files:
            url = _join(self.output.url, relative_path)
            if is_directory:
                files.extend(_directory_files(path, url))
            else:
                files.append((path, url))
        await self._upload(files)

    async def _upload(self, files: list[tuple[str, str]]) -> None:
        """Upload each `(path, url)` in one FTP session, then record them."""
        assert self.output is not None

        def run(ftp: ftplib.FTP) -> None:
            for path, url in files:
                remote = _remote_path(url)
                _make_parents(ftp, posixpath.dirname(remote))
                with open(path, "rb") as f:
                    ftp.storbinary(f"STOR {remote}", f)
                logger.info("Uploaded %s to %s", path, redact_url(url))

        await asyncio.to_thread(_with_session, self.output.url, "upload", run)
        for path, url in files:
            self._record_upload(path, url)


def _remote_path(url: str) -> str:
    """The path to send to the server for `url`, relative to the login directory."""
    path = urlsplit(url).path
    return unquote(path.removeprefix("/"))


def _join(url: str, relative_path: str) -> str:
    """Append `relative_path` to the path of `url`, each segment escaped."""
    parts = urlsplit(url)
    segments = [quote(os.fsencode(s), safe="") for s in relative_path.split("/")]
    path = "/".join([parts.path.rstrip("/"), *segments])
    return urlunsplit(parts._replace(path=path))


def _directory_files(directory: str, url: str) -> list[tuple[str, str]]:
    """`(path, url)` of each file under `directory`, `url` plus its relative path."""
    files: list[tuple[str, str]] = []
    for root, _, names in os.walk(directory):
        for name in names:
            path = os.path.join(root, name)
            files.append((path, _join(url, os.path.relpath(path, directory))))
    return files


@contextmanager
def _session(url: str) -> Iterator[ftplib.FTP]:
    """A logged-in, passive, binary FTP session with the server of `url`."""
    parts = urlsplit(url)
    if not parts.hostname:
        raise ValueError(f"FTP URL has no host: {redact_url(url)}")
    ftp: ftplib.FTP
    if parts.scheme.lower() == "ftps":
        ftp = ftplib.FTP_TLS(  # noqa: S321 - TLS, certificate checked
            timeout=_TIMEOUT_SECONDS, context=ssl.create_default_context()
        )
    else:
        # Plain FTP is what public archives serve; ftps:// is there for TLS.
        ftp = ftplib.FTP(timeout=_TIMEOUT_SECONDS)  # noqa: S321
    try:
        ftp.connect(parts.hostname, parts.port or ftplib.FTP_PORT)
        user = unquote(parts.username) if parts.username else "anonymous"
        password = unquote(parts.password or "") if parts.username else "anonymous@"
        try:
            # FTP_TLS.login sends AUTH TLS first.
            ftp.login(user, password)
        except ftplib.error_perm as e:
            raise FtpError(f"FTP login to {redact_url(url)} was refused: {e}") from None
        if isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
        ftp.set_pasv(True)
        ftp.voidcmd("TYPE I")
        yield ftp
    finally:
        # quit() on a session that never connected raises AttributeError.
        try:
            ftp.quit()
        except (OSError, EOFError, AttributeError, ftplib.Error):
            ftp.close()


def _with_session(url: str, what: str, run: Callable[[ftplib.FTP], None]) -> None:
    """Call `run` with a session for `url`, retrying transient failures.

    Each attempt opens a new session and starts `run` again. A 5xx reply
    raises `FtpError` naming `url` without its credentials.
    """
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            with _session(url) as ftp:
                run(ftp)
            return
        except ftplib.error_perm as e:
            raise FtpError(
                f"FTP {what} of {redact_url(url)} was refused by the server: {e}"
            ) from None
        except Exception as e:
            if attempt == _ATTEMPTS or not _is_transient(e):
                raise
            delay = 2 ** (attempt - 1)
            logger.warning(
                "FTP %s of %s failed, retrying in %d s: %s",
                what,
                redact_url(url),
                delay,
                e,
            )
            time.sleep(delay)


def _is_transient(error: Exception) -> bool:
    """True if a later attempt may succeed after `error`.

    A 4xx reply, a dropped or refused connection, a timeout, or a name
    that didn't resolve. A certificate the client rejects won't pass on a
    later attempt.
    """
    if isinstance(error, ssl.SSLError):
        return False
    return isinstance(
        error,
        (ftplib.error_temp, EOFError, ConnectionError, TimeoutError, socket.gaierror),
    )


def _download_file(ftp: ftplib.FTP, remote: str, path: str) -> None:
    """RETR `remote` into `path` through a temporary file next to it."""
    directory, name = os.path.split(path)
    os.makedirs(directory, exist_ok=True)
    partial = os.path.join(directory, f".{name}.{uuid.uuid4().hex}.part")
    try:
        with open(partial, "wb") as f:
            ftp.retrbinary(f"RETR {remote}", f.write)
        os.replace(partial, path)
    finally:
        if os.path.lexists(partial):
            os.remove(partial)


def _download_tree(ftp: ftplib.FTP, remote: str, local: str, depth: int) -> None:
    """Download the directory `remote`, and everything under it, into `local`."""
    if depth > _MAX_DEPTH:
        raise FtpError(
            f"FTP directory {remote!r} is nested more than {_MAX_DEPTH} deep"
        )
    os.makedirs(local, exist_ok=True)
    for name, is_dir in _list(ftp, remote):
        child_remote = posixpath.join(remote, name) if remote else name
        child_local = os.path.join(local, name)
        if is_dir:
            _download_tree(ftp, child_remote, child_local, depth + 1)
        else:
            _download_file(ftp, child_remote, child_local)


def _list(ftp: ftplib.FTP, remote: str) -> list[tuple[str, bool]]:
    """`(name, is_directory)` of each entry of the directory `remote`.

    MLSD where the server has it; NLST otherwise, telling directories by
    whether CWD into them succeeds. Names are reduced to their last path
    segment, and ``.`` and ``..`` are left out, so no entry leads outside
    the directory being staged.
    """
    entries: list[tuple[str, bool | None]] = []
    try:
        for name, facts in ftp.mlsd(remote, facts=["type"]):
            kind = facts.get("type", "").lower()
            entries.append((name, {"dir": True, "file": False}.get(kind)))
    except ftplib.error_perm:
        entries = [(name, None) for name in ftp.nlst(*([remote] if remote else []))]
    listed: list[tuple[str, bool]] = []
    for raw, is_dir in entries:
        name = _entry_name(raw)
        if name is None:
            continue
        child = posixpath.join(remote, name) if remote else name
        listed.append((name, _is_dir(ftp, child) if is_dir is None else is_dir))
    return listed


def _entry_name(raw: str) -> str | None:
    """The last path segment of a listed entry; None for ``.``, ``..`` or nothing."""
    name = raw.rstrip("/").rpartition("/")[2]
    if name in {"", ".", ".."} or "\0" in name:
        return None
    return name


def _is_dir(ftp: ftplib.FTP, remote: str) -> bool:
    """True if CWD into `remote` succeeds; returns to the previous directory."""
    if not remote:
        return True
    here = ftp.pwd()
    try:
        ftp.cwd(remote)
    except ftplib.error_perm:
        return False
    ftp.cwd(here)
    return True


def _make_parents(ftp: ftplib.FTP, remote_dir: str) -> None:
    """Create `remote_dir` and its parents; existing ones are left alone.

    A failed MKD is ignored: the directory may exist. If it doesn't, the
    STOR that follows fails with the server's reply.
    """
    segments = remote_dir.split("/")
    for i in range(1, len(segments) + 1):
        prefix = "/".join(segments[:i])
        if prefix in {"", "/"} or segments[i - 1] == "":
            continue
        with contextlib.suppress(ftplib.error_perm):
            ftp.mkd(prefix)
