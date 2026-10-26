"""Tests for HTTP(S) outputs, uploaded by `HttpFilerStrategy` with PUT.

Uploads go to a recording server in a thread, so the requests, headers
and bytes on the wire are those of a real upload.
"""

import asyncio
import gzip
import http.server
import io
import logging
import os
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote_to_bytes

import pytest
import requests

from poiesis.api.tes.models import TesFileType, TesInput, TesOutput
from poiesis.core.services.filer.filer_strategy_factory import (
    can_output,
    create_output_strategy,
)
from poiesis.core.services.filer.strategy import filer_strategy, http_filer
from poiesis.core.services.filer.tif import Tif
from poiesis.core.services.filer.tof import Tof

MIB = 1024 * 1024
ERROR_BODY = b"<Error><Code>SignatureDoesNotMatch</Code></Error>"


@dataclass
class Request:
    """A request the server received."""

    route: str
    path: str
    headers: dict[str, str]


class Handler(http.server.BaseHTTPRequestHandler):
    """Answers a PUT according to the first segment of its path.

    - `/store/<key>` stores the body under `/<key>`.
    - `/redirect/<status>/<path>` redirects to `/<path>`.
    - `/early307/<path>` redirects to `/<path>` and hangs up, unread.
    - `/status/<status>/...` answers with that status.
    - `/flaky/<n>/<status>/<key>` fails n times, then stores.
    - `/huge-error/...` answers 403 with a 64 MiB body.
    - `/loop/...` redirects to itself.

    A flaky failure answers with the status, or hangs up if it's `drop`.
    """

    protocol_version = "HTTP/1.1"
    server: "Server"

    def log_message(self, format, *args):
        """Keep the test output quiet."""

    def do_GET(self):
        """Serve an input file."""
        self._reply(200, body=b"input")

    def do_PUT(self):
        """Record the request, then answer it according to its route."""
        path, _, query = self.path.partition("?")
        suffix = f"?{query}" if query else ""
        route, _, rest = path.lstrip("/").partition("/")
        self.server.requests.append(Request(route, self.path, dict(self.headers)))
        if route == "early307":
            self.close_connection = True
            self._reply(307, location=self.server.url(f"/{rest}{suffix}"))
            return
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if route == "store":
            self.server.store[unquote_to_bytes(f"/{rest}")] = body
            self._reply(200)
        elif route == "redirect":
            status, _, target = rest.partition("/")
            self._reply(int(status), location=f"/{target}{suffix}")
        elif route == "status":
            status = int(rest.partition("/")[0])
            self._reply(status, body=ERROR_BODY if status >= 400 else b"")
        elif route == "flaky":
            failures, status, key = rest.split("/", 2)
            failed = self.server.failures.get(path, 0)
            if failed < int(failures):
                self.server.failures[path] = failed + 1
                if status == "drop":
                    self.close_connection = True
                else:
                    self._reply(int(status))
                return
            self.server.store[unquote_to_bytes(f"/{key}")] = body
            self._reply(200)
        elif route == "huge-error":
            self._send_huge_error()
        elif route == "loop":
            self._reply(307, location=self.path)

    def _reply(self, status: int, body: bytes = b"", location: str = "") -> None:
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_huge_error(self) -> None:
        self.send_response(403)
        self.send_header("Content-Length", str(64 * MIB))
        self.end_headers()
        try:
            for _ in range(64):
                self.wfile.write(b"x" * MIB)
        except OSError:
            self.close_connection = True
            self.server.whole_error_sent = False
        else:
            self.server.whole_error_sent = True
        self.server.error_done.set()


class Server(http.server.ThreadingHTTPServer):
    """A recording HTTP server, serving from a thread."""

    def __init__(self) -> None:
        """Start serving on a free port of 127.0.0.1."""
        super().__init__(("127.0.0.1", 0), Handler)
        self.store: dict[bytes, bytes] = {}
        self.requests: list[Request] = []
        self.failures: dict[str, int] = {}
        self.whole_error_sent: bool | None = None
        self.error_done = threading.Event()
        # A short poll interval lets shutdown() return quickly.
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()

    def url(self, path: str) -> str:
        """The URL of `path` on this server."""
        host, port = self.server_address[:2]
        return f"http://{host}:{port}{path}"


@pytest.fixture
def server() -> Iterator[Server]:
    """A recording server, shut down after the test."""
    srv = Server()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def pvc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary directory standing in for the task's volume."""
    monkeypatch.setattr(filer_strategy, "FILER_PVC_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The delays before retries, which pass at once."""
    delays: list[float] = []
    monkeypatch.setattr(http_filer.time, "sleep", delays.append)
    return delays


def write(pvc: Path, path: str, data: bytes) -> None:
    """Write `data` at the executor path `path` on the task's volume."""
    file = pvc / path.lstrip("/")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)


def upload(
    url: str,
    path: str,
    file_type: TesFileType = TesFileType.FILE,
    path_prefix: str | None = None,
) -> None:
    """Upload the output at `path` to `url`, as TOF does."""
    output = TesOutput(url=url, path=path, type=file_type, path_prefix=path_prefix)
    asyncio.run(create_output_strategy(url, output).upload())


def fake_put(
    monkeypatch: pytest.MonkeyPatch, responses: list[tuple[int, str]]
) -> list[str]:
    """Answer each PUT with the next `(status, Location)`; return the URLs."""
    urls: list[str] = []

    def put(url: str, **_: object) -> requests.Response:
        status, location = responses[len(urls)]
        urls.append(url)
        response = requests.Response()
        response.status_code = status
        if location:
            response.headers["Location"] = location
        response.raw = io.BytesIO(b"")
        return response

    monkeypatch.setattr(http_filer.requests, "put", put)
    return urls


def test_http_and_https_are_output_schemes():
    """HTTP(S) output URLs are accepted, so tasks using them aren't refused."""
    assert can_output("http://example.org/out.txt")
    assert can_output("https://example.org/out.txt")


@pytest.mark.parametrize(
    "data",
    [
        gzip.compress(b"@r1\nACGT\n+\nIIII\n" * 200),
        b"first\r\nsecond\r\n",
        "café, x ≥ 1\n".encode(),
        b"",
    ],
    ids=["gzip", "crlf", "utf8", "empty"],
)
def test_file_is_sent_as_is_with_its_length(server, pvc, data):
    """The bytes arrive unchanged, with Content-Length and no chunking."""
    write(pvc, "/outputs/out", data)
    upload(server.url("/store/out?X-Amz-Signature=abc"), "/outputs/out")
    assert server.store == {b"/out": data}
    (request,) = server.requests
    assert request.headers["Content-Length"] == str(len(data))
    assert "Transfer-Encoding" not in request.headers
    assert "Expect" not in request.headers


@pytest.mark.parametrize("status", [307, 308])
def test_redirect_that_keeps_the_put_is_followed(server, pvc, status):
    """The file is sent again to the new URL."""
    write(pvc, "/outputs/out", b"data")
    upload(server.url(f"/redirect/{status}/store/out"), "/outputs/out")
    assert server.store == {b"/out": b"data"}
    assert [r.route for r in server.requests] == ["redirect", "store"]


def test_redirect_sent_before_the_file_is_read_is_followed(server, pvc):
    """A server may redirect without reading the file and hang up."""
    data = os.urandom(16 * MIB)
    write(pvc, "/outputs/out", data)
    upload(server.url("/early307/store/out"), "/outputs/out")
    assert server.store == {b"/out": data}


@pytest.mark.parametrize("status", [301, 302, 303])
def test_redirect_that_drops_the_file_fails(server, pvc, status):
    """Following it would resend the PUT without the file or as a GET."""
    write(pvc, "/outputs/out", b"data")
    with pytest.raises(requests.HTTPError, match=f"returned {status}"):
        upload(server.url(f"/redirect/{status}/store/out"), "/outputs/out")
    assert server.store == {}


def test_https_upload_is_not_redirected_off_https(monkeypatch, pvc):
    """The file isn't sent in cleartext after starting out over HTTPS."""
    write(pvc, "/outputs/out", b"data")
    urls = fake_put(monkeypatch, [(307, "http://storage.example/out")])
    with pytest.raises(requests.HTTPError, match="isn't HTTPS"):
        upload("https://gateway.example/out", "/outputs/out")
    assert urls == ["https://gateway.example/out"]


def test_http_upload_may_be_redirected_to_https(monkeypatch, pvc):
    """Moving to HTTPS only makes the upload safer."""
    write(pvc, "/outputs/out", b"data")
    urls = fake_put(monkeypatch, [(307, "https://storage.example/out"), (200, "")])
    upload("http://gateway.example/out", "/outputs/out")
    assert urls == ["http://gateway.example/out", "https://storage.example/out"]


def test_rejection_reports_status_and_body_without_query(server, pvc):
    """Object stores explain a rejection in the body; the query is secret."""
    write(pvc, "/outputs/out", b"data")
    with pytest.raises(requests.HTTPError) as error:
        upload(server.url("/status/403/out?X-Amz-Signature=secret"), "/outputs/out")
    assert f"returned 403: {ERROR_BODY.decode()}" in str(error.value)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("status", [304, 307, 400, 403, 404])
def test_other_responses_fail_without_retries(server, pvc, sleeps, status):
    """Responses outside 2xx fail the upload; a 307 without Location too."""
    write(pvc, "/outputs/out", b"data")
    with pytest.raises(requests.HTTPError, match=f"returned {status}"):
        upload(server.url(f"/status/{status}/out"), "/outputs/out")
    assert len(server.requests) == 1
    assert sleeps == []


def test_only_the_start_of_an_error_body_is_read(server, pvc):
    """A huge error body can't exhaust memory."""
    write(pvc, "/outputs/out", b"data")
    with pytest.raises(requests.HTTPError) as error:
        upload(server.url("/huge-error/out"), "/outputs/out")
    assert len(str(error.value).partition("returned 403: ")[2]) == 1024
    assert server.error_done.wait(10)
    assert server.whole_error_sent is False


def test_redirect_loop_stops(server, pvc):
    """An upload follows at most 10 redirects."""
    write(pvc, "/outputs/out", b"data")
    with pytest.raises(requests.TooManyRedirects):
        upload(server.url("/loop/out"), "/outputs/out")
    assert len(server.requests) == 11


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_failure_is_retried(server, pvc, sleeps, status):
    """Two failures in a row still end in an upload."""
    write(pvc, "/outputs/out", b"data")
    upload(server.url(f"/flaky/2/{status}/out"), "/outputs/out")
    assert server.store == {b"/out": b"data"}
    assert len(server.requests) == 3
    assert sleeps == [1, 2]


def test_dropped_connection_is_retried(server, pvc, sleeps):
    """A connection closed without an answer is retried."""
    write(pvc, "/outputs/out", b"data")
    upload(server.url("/flaky/1/drop/out"), "/outputs/out")
    assert server.store == {b"/out": b"data"}
    assert sleeps == [1]


def test_retries_give_up_after_three_attempts(server, pvc, sleeps):
    """The third failure fails the upload."""
    write(pvc, "/outputs/out", b"data")
    with pytest.raises(requests.HTTPError, match="returned 503"):
        upload(server.url("/flaky/3/503/out"), "/outputs/out")
    assert len(server.requests) == 3
    assert sleeps == [1, 2]


def test_retry_starts_again_from_the_output_url(server, pvc):
    """A server that signs uploads gets to sign the retry afresh."""
    write(pvc, "/outputs/out", b"data")
    upload(server.url("/redirect/307/flaky/1/503/out"), "/outputs/out")
    routes = [r.route for r in server.requests]
    assert routes == ["redirect", "flaky", "redirect", "flaky"]
    assert server.store == {b"/out": b"data"}


def test_failed_connection_is_retried_and_hides_the_query(pvc, sleeps):
    """requests quotes the URL in the error, but not its query."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    write(pvc, "/outputs/out", b"data")
    with pytest.raises(requests.ConnectionError) as error:
        upload(f"http://127.0.0.1:{port}/out?X-Amz-Signature=secret", "/outputs/out")
    assert "secret" not in str(error.value)
    assert sleeps == [1, 2]


def test_directory_files_keep_their_names_and_the_query(server, pvc):
    """Names are escaped into the path; the query may carry a token."""
    names = ["result#1.txt", "a?b.txt", "50%25.txt", "a b.txt", "café.txt", "sub/y"]
    for name in names:
        write(pvc, f"/outputs/dir/{name}", name.encode())
    upload(server.url("/store/dir/?token=abc"), "/outputs/dir", TesFileType.DIRECTORY)
    assert server.store == {f"/dir/{name}".encode(): name.encode() for name in names}
    assert all(r.path.endswith("?token=abc") for r in server.requests)


def test_directory_file_with_a_non_utf8_name_keeps_it(server, pvc):
    """The URL carries the name's bytes as they are on disk."""
    name = b"name-\xe9.txt"
    (pvc / "outputs" / "dir").mkdir(parents=True)
    try:
        with open(os.path.join(os.fsencode(pvc), b"outputs/dir/", name), "wb") as f:
            f.write(b"x")
    except OSError:
        pytest.skip("this filesystem only takes UTF-8 file names")
    upload(server.url("/store/dir"), "/outputs/dir", TesFileType.DIRECTORY)
    assert server.store == {b"/dir/" + name: b"x"}


def test_glob_uploads_matching_files_and_directories(server, pvc):
    """A matched directory is uploaded with every file under it."""
    write(pvc, "/outputs/glob/x.txt", b"x")
    write(pvc, "/outputs/glob/y.log", b"y")
    write(pvc, "/outputs/glob/d.txt/inner.bin", b"inner")
    upload(
        server.url("/store/glob"), "/outputs/glob/*.txt", path_prefix="/outputs/glob/"
    )
    assert server.store == {b"/glob/x.txt": b"x", b"/glob/d.txt/inner.bin": b"inner"}


def test_missing_output_fails(server, pvc):
    """A declared output that the executors didn't write fails the upload."""
    with pytest.raises(FileNotFoundError):
        upload(server.url("/store/out"), "/outputs/missing.txt")
    assert server.requests == []


def test_filer_logs_leave_out_the_query(server, pvc, caplog, monkeypatch):
    """A presigned URL's query is its signature, so logs don't carry it."""
    # poiesis.core doesn't propagate to the root logger, where caplog listens.
    monkeypatch.setattr(logging.getLogger("poiesis.core"), "propagate", True)
    caplog.set_level(logging.INFO)
    write(pvc, "/outputs/out", b"data")
    query = "?X-Amz-Signature=secret"
    ok = TesOutput(
        url=server.url(f"/redirect/307/store/out{query}"), path="/outputs/out"
    )
    asyncio.run(Tof("task", [ok]).file())
    rejected = TesOutput(url=server.url(f"/status/403/out{query}"), path="/outputs/out")
    with pytest.raises(requests.HTTPError):
        asyncio.run(Tof("task", [rejected]).file())
    tes_input = TesInput(url=server.url(f"/in{query}"), path="/inputs/in")
    asyncio.run(Tif("task", [tes_input]).file())
    assert server.store == {b"/out": b"data"}
    assert "Uploaded" in caplog.text
    assert "TOF failed" in caplog.text
    assert "secret" not in caplog.text
