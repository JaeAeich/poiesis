"""HTTP filer strategy — downloads inputs with GET, uploads outputs with PUT.

Outputs can go to presigned upload URLs (S3, Google Cloud Storage and
others), so the filer needs no storage credentials. A presigned URL is
signed for one object, but the URL of each file of a `DIRECTORY` or glob
output is derived from the output URL; those outputs need a server that
signs each upload as it arrives and redirects it with a 307 or 308.
"""

import logging
import os
from http import HTTPStatus
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.services.filer.strategy.filer_strategy import (
    InputFilerStrategy,
    OutputFilerStrategy,
)

logger = logging.getLogger(__name__)

#: Redirects an upload follows, resending the file. requests turns a PUT
#: redirected with a 302 or 303 into a GET and resends one redirected with
#: a 301 without the file, so a success would pass for a successful upload;
#: those redirects fail the upload instead.
_UPLOAD_REDIRECTS = (HTTPStatus.TEMPORARY_REDIRECT, HTTPStatus.PERMANENT_REDIRECT)
_MAX_REDIRECTS = 10


class HttpFilerStrategy(InputFilerStrategy, OutputFilerStrategy):
    """Filer strategy for HTTP and HTTPS inputs and outputs."""

    def __init__(self, payload: TesInput | TesOutput):
        """Initialise with the TES input or output."""
        super().__init__(payload)
        self.input = self.payload if isinstance(self.payload, TesInput) else None
        self.output = self.payload if isinstance(self.payload, TesOutput) else None

    async def download_input_file(self, container_path: str) -> None:
        """Stream the input file from the HTTP(S) URL to `container_path`."""
        assert self.input is not None
        if self.input.url is None:
            raise ValueError("URL is required")

        response = requests.get(self.input.url, stream=True, timeout=30)

        with open(container_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    async def download_input_directory(self, container_path: str) -> None:
        """HTTP directory listing is not standardised; refuse."""
        raise NotImplementedError(
            "Downloading directories over HTTP/HTTPS is not supported"
        )

    async def upload_output_file(self, container_path: str) -> None:
        """PUT the output file at `container_path` to the output URL."""
        assert self.output is not None
        _put(container_path, self.output.url)

    async def upload_output_directory(self, container_path: str) -> None:
        """PUT each file under `container_path` to the output URL.

        A file's URL is the output URL with the file's path relative to
        `container_path` appended to its path.
        """
        assert self.output is not None
        if not os.path.isdir(container_path):
            raise FileNotFoundError(f"Output directory not found: {container_path}")
        _put_directory(container_path, self.output.url)

    async def upload_glob(self, glob_files: list[tuple[str, str, bool]]) -> None:
        """PUT each glob match to the output URL plus its relative path.

        A matched directory is uploaded with every file under it.
        """
        assert self.output is not None
        for path, relative_path, is_directory in glob_files:
            url = _join(self.output.url, relative_path)
            if is_directory:
                _put_directory(path, url)
            else:
                _put(path, url)


def _put_directory(directory: str, url: str) -> None:
    """PUT each file under `directory` to `url` plus its relative path."""
    for root, _, files in os.walk(directory):
        for name in files:
            path = os.path.join(root, name)
            _put(path, _join(url, os.path.relpath(path, directory)))


def _put(path: str, url: str) -> None:
    """PUT the file at `path` to `url`, following 307 and 308 redirects."""
    target = url
    for _ in range(_MAX_REDIRECTS + 1):
        with open(path, "rb") as f:
            # requests streams a file object and sets Content-Length from its
            # size, but sends an empty one with chunked encoding, which
            # presigned upload URLs such as S3's reject; b"" is sent with a
            # Content-Length of 0.
            data = f if os.fstat(f.fileno()).st_size > 0 else b""
            response = requests.put(
                target, data=data, allow_redirects=False, timeout=30
            )
        location = response.headers.get("Location")
        if response.status_code in _UPLOAD_REDIRECTS and location:
            redirect = urljoin(target, location)
            # An upload to an HTTPS URL is never resent in cleartext.
            if urlsplit(url).scheme == "https" and urlsplit(redirect).scheme != "https":
                raise requests.HTTPError(
                    f"PUT {_without_query(target)} was redirected to "
                    f"{_without_query(redirect)}, which isn't HTTPS",
                    response=response,
                )
            target = redirect
            continue
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            # Object stores explain a rejection, such as an expired or
            # mismatched signature, in the response body.
            body = response.text[:1024].strip()
            raise requests.HTTPError(
                f"PUT {_without_query(target)} returned {response.status_code}"
                f"{': ' + body if body else ''}",
                response=response,
            )
        logger.info("Uploaded %s to %s", path, _without_query(url))
        return
    raise requests.TooManyRedirects(
        f"PUT {_without_query(url)} stopped after {_MAX_REDIRECTS} redirects"
    )


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


def _without_query(url: str) -> str:
    """`url` for logs and errors: a presigned URL's query is its signature."""
    return urlunsplit(urlsplit(url)._replace(query="", fragment=""))
