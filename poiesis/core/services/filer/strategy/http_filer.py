"""HTTP filer strategy — downloads inputs with GET, uploads outputs with PUT.

An input is staged only from a 2xx response. It is written to a temporary
file next to its path and renamed into place once the whole body has
arrived, so a failed download leaves nothing at the input's path.

Outputs can go to presigned upload URLs (S3, Google Cloud Storage and
others), so the filer needs no storage credentials. A presigned URL is
signed for one object, but the URL of each file of a `DIRECTORY` or glob
output is derived from the output URL; those outputs need a server that
signs each upload as it arrives and redirects it with a 307 or 308.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit

import requests

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.services.filer.strategy.filer_strategy import (
    InputFilerStrategy,
    OutputFilerStrategy,
    redact_url,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

#: Redirects an upload follows, resending the file. requests turns a PUT
#: redirected with a 302 or 303 into a GET and resends one redirected with
#: a 301 without the file, so a success would pass for a successful upload;
#: those redirects fail the upload instead.
_UPLOAD_REDIRECTS = (HTTPStatus.TEMPORARY_REDIRECT, HTTPStatus.PERMANENT_REDIRECT)
#: Redirects a download follows.
_DOWNLOAD_REDIRECTS = (
    HTTPStatus.MOVED_PERMANENTLY,
    HTTPStatus.FOUND,
    HTTPStatus.SEE_OTHER,
    *_UPLOAD_REDIRECTS,
)
_MAX_REDIRECTS = 10

#: Responses after which a later attempt at a request may succeed.
_TRANSIENT_STATUSES = frozenset(
    {
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)
_ATTEMPTS = 3

#: Query values shorter than this are left in a quoted error body: cutting
#: every ``1`` or ``json`` from it would garble it without hiding a secret.
_MIN_SECRET_LENGTH = 8


class HttpFilerStrategy(InputFilerStrategy, OutputFilerStrategy):
    """Filer strategy for HTTP and HTTPS inputs and outputs."""

    def __init__(self, payload: TesInput | TesOutput) -> None:
        """Initialise with the TES input or output."""
        super().__init__(payload)
        self.input = self.payload if isinstance(self.payload, TesInput) else None
        self.output = self.payload if isinstance(self.payload, TesOutput) else None
        #: Headers sent with the download, such as those a DRS server's
        #: ``/access`` answer names for its URL. Sent on redirects only to
        #: the same scheme, host and port.
        self.headers: dict[str, str] = {}

    async def download_input_file(self, container_path: str) -> None:
        """Stream the input file from the HTTP(S) URL to `container_path`."""
        assert self.input is not None
        if self.input.url is None:
            raise ValueError("URL is required")

        _get(self.input.url, container_path, self.headers)

    async def download_input_directory(self, container_path: str) -> None:
        """HTTP directory listing is not standardised; refuse."""
        raise NotImplementedError(
            "Downloading directories over HTTP/HTTPS is not supported"
        )

    async def upload_output_file(self, container_path: str) -> None:
        """PUT the output file at `container_path` to the output URL."""
        assert self.output is not None
        _put(container_path, self.output.url)
        self._record_upload(container_path, self.output.url)

    async def upload_output_directory(self, container_path: str) -> None:
        """PUT each file under `container_path` to the output URL.

        A file's URL is the output URL with the file's path relative to
        `container_path` appended to its path.
        """
        assert self.output is not None
        if not os.path.isdir(container_path):
            raise FileNotFoundError(f"Output directory not found: {container_path}")
        for path, url in _put_directory(container_path, self.output.url):
            self._record_upload(path, url)

    async def upload_glob(self, glob_files: list[tuple[str, str, bool]]) -> None:
        """PUT each glob match to the output URL plus its relative path.

        A matched directory is uploaded with every file under it.
        """
        assert self.output is not None
        for path, relative_path, is_directory in glob_files:
            url = _join(self.output.url, relative_path)
            if is_directory:
                for file_path, file_url in _put_directory(path, url):
                    self._record_upload(file_path, file_url)
            else:
                _put(path, url)
                self._record_upload(path, url)


def _put_directory(directory: str, url: str) -> list[tuple[str, str]]:
    """PUT each file under `directory` to `url` plus its relative path.

    Returns the `(path, url)` of each file uploaded.
    """
    uploaded: list[tuple[str, str]] = []
    for root, _, files in os.walk(directory):
        for name in files:
            path = os.path.join(root, name)
            file_url = _join(url, os.path.relpath(path, directory))
            _put(path, file_url)
            uploaded.append((path, file_url))
    return uploaded


def _get(url: str, path: str, headers: dict[str, str] | None = None) -> None:
    """GET `url` into the file at `path`, retrying transient failures.

    The body goes to a temporary file in the directory of `path`, renamed to
    `path` once it is complete: `path` never holds a partial download or the
    body of an error response.
    """
    directory, name = os.path.split(path)
    partial = os.path.join(directory, f".{name}.{uuid.uuid4().hex}.part")
    try:
        _retry(
            lambda: _get_once(url, partial, headers or {}),
            f"Download of {redact_url(url)}",
        )
        os.replace(partial, path)
    finally:
        if os.path.lexists(partial):
            os.remove(partial)
    logger.info("Downloaded %s to %s", redact_url(url), path)


def _get_once(url: str, path: str, headers: dict[str, str]) -> None:
    """GET `url` into the file at `path`, following redirects.

    `headers` go with each request to the origin of `url`, not elsewhere.
    """
    origin = _origin(url)
    target = url
    for _ in range(_MAX_REDIRECTS + 1):
        sent = headers if _origin(target) == origin else {}
        with _request("GET", target, headers=sent) as response:
            location = response.headers.get("Location")
            if response.status_code in _DOWNLOAD_REDIRECTS and location:
                target = _redirect("GET", target, location, response)
                continue
            _raise_for_status("GET", target, response)
            with open(path, "wb") as f:
                f.writelines(response.iter_content(chunk_size=8192))
        return
    raise requests.TooManyRedirects(
        f"GET {redact_url(url)} stopped after {_MAX_REDIRECTS} redirects"
    )


def _origin(url: str) -> tuple[str, str | None, int | None]:
    """Scheme, host and port of `url`."""
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.hostname, parts.port


def _put(path: str, url: str) -> None:
    """PUT the file at `path` to `url`, retrying transient failures.

    Each attempt starts again from `url`, so a server that signs uploads
    signs the retry afresh. Repeating a PUT of the same file to the same
    URL is safe even if an earlier attempt got through.
    """
    _retry(lambda: _put_once(path, url), f"Upload of {path}")


def _retry(attempt_once: Callable[[], None], what: str) -> None:
    """Call `attempt_once` until it succeeds, up to `_ATTEMPTS` times.

    Only a transient failure (`_is_transient`) is followed by another
    attempt, after a delay that doubles each time. `what` names the
    transfer in the log.
    """
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            attempt_once()
            return
        except requests.RequestException as e:
            if attempt == _ATTEMPTS or not _is_transient(e):
                raise
            delay = 2 ** (attempt - 1)
            logger.warning("%s failed, retrying in %d s: %s", what, delay, e)
            time.sleep(delay)


def _is_transient(error: requests.RequestException) -> bool:
    """True if a later attempt at the request that raised `error` may succeed."""
    if isinstance(error, requests.HTTPError):
        return (
            error.response is not None
            and error.response.status_code in _TRANSIENT_STATUSES
        )
    # A certificate the client rejects won't pass on a later attempt either.
    # ChunkedEncodingError is a response body that ended early.
    return isinstance(
        error,
        (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    ) and not isinstance(error, requests.exceptions.SSLError)


def _put_once(path: str, url: str) -> None:
    """PUT the file at `path` to `url`, following 307 and 308 redirects."""
    target = url
    for _ in range(_MAX_REDIRECTS + 1):
        with _send(path, target) as response:
            location = response.headers.get("Location")
            if response.status_code in _UPLOAD_REDIRECTS and location:
                target = _redirect("PUT", target, location, response)
                continue
            _raise_for_status("PUT", target, response)
        logger.info("Uploaded %s to %s", path, redact_url(url))
        return
    raise requests.TooManyRedirects(
        f"PUT {redact_url(url)} stopped after {_MAX_REDIRECTS} redirects"
    )


def _redirect(
    method: str, target: str, location: str, response: requests.Response
) -> str:
    """The URL that `location`, sent in answer to `target`, redirects to.

    A transfer that has reached an HTTPS URL never goes on in cleartext:
    such a redirect raises.
    """
    redirect = urljoin(target, location)
    if urlsplit(target).scheme == "https" and urlsplit(redirect).scheme != "https":
        raise requests.HTTPError(
            f"{method} {redact_url(target)} was redirected to "
            f"{redact_url(redirect)}, which isn't HTTPS",
            response=response,
        )
    return redirect


def _raise_for_status(method: str, target: str, response: requests.Response) -> None:
    """Raise unless `response`, the answer to `target`, is a 2xx.

    Object stores explain a rejection, such as an expired or mismatched
    signature, at the start of the response body, so up to 1 KiB of it is
    quoted. Values of the query of `target` are cut from it: S3 echoes the
    signature it was sent.
    """
    if HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
        return
    body = response.raw.read(1024, decode_content=True).decode(errors="replace")
    query = urlsplit(target).query
    # As sent and decoded: the body may quote either form.
    raw = [pair.partition("=")[2] for pair in query.split("&")]
    for value in [*raw, *(value for _, value in parse_qsl(query))]:
        if len(value) >= _MIN_SECRET_LENGTH:
            body = body.replace(value, "<redacted>")
    body = body.strip()
    raise requests.HTTPError(
        f"{method} {redact_url(target)} returned {response.status_code}"
        f"{': ' + body if body else ''}",
        response=response,
    )


def _request(method: str, url: str, **kwargs: Any) -> requests.Response:
    """Send one request to `url`, without following redirects.

    The response is streamed: its body isn't read here.
    """
    try:
        return requests.request(
            method, url, allow_redirects=False, timeout=30, stream=True, **kwargs
        )
    except requests.RequestException as e:
        # requests quotes the URL, query included, in the message of
        # errors such as a failed connection.
        query = urlsplit(url).query
        if not query:
            raise
        raise type(e)(str(e).replace(query, "<redacted>")) from None


def _send(path: str, url: str) -> requests.Response:
    """PUT the file at `path` to `url` once, without following redirects.

    The response is streamed: its body isn't read, except for up to 1 KiB
    of an error.
    """
    with open(path, "rb") as f:
        # requests streams a file object and sets Content-Length from its
        # size, but sends an empty one with chunked encoding, which presigned
        # upload URLs such as S3's reject; b"" is sent with a Content-Length
        # of 0.
        data = f if os.fstat(f.fileno()).st_size > 0 else b""
        return _request("PUT", url, data=data)


def _join(url: str, relative_path: str) -> str:
    """Append `relative_path` to the path of `url`, keeping its query.

    Each segment is escaped, so a file name containing a character such as
    #, ? or % stays part of the path. The query may carry a token for the
    server that signs uploads.
    """
    parts = urlsplit(url)
    # Quote each name's bytes on disk: os.walk and glob return a name that
    # isn't valid UTF-8 with surrogate escapes, which quote can't encode.
    segments = [quote(os.fsencode(s), safe="") for s in relative_path.split("/")]
    path = "/".join([parts.path.rstrip("/"), *segments])
    return urlunsplit(parts._replace(path=path))
