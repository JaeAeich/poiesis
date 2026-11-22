"""Google Workload Identity Federation for TIF/TOF (#29).

`GcsWorkloadIdentity` trades the projected ServiceAccount token at a
mocked Google STS (and IAM Credentials, to impersonate a service
account). The last test runs a `gs://` input through obstore against a
local server playing STS, IAM Credentials and GCS, so it also shows that
obstore calls the provider and sends its token.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from poiesis.api.tes.models import TesInput
from poiesis.core.constants import (
    GCS_IDENTITY_TOKEN_FILE_ENV,
    GCS_SERVICE_ACCOUNT_ENV,
    GCS_WORKLOAD_IDENTITY_PROVIDER_ENV,
)
from poiesis.core.services.filer.strategy import filer_strategy, gcs_identity
from poiesis.core.services.filer.strategy.gcs_identity import (
    GcsIdentityError,
    GcsWorkloadIdentity,
    token_audience,
)
from poiesis.core.services.filer.strategy.object_store_filer import (
    ObjectStoreFilerStrategy,
    ObjectUrl,
    gcs_credential_provider,
    make_store,
)

PROVIDER = (
    "//iam.googleapis.com/projects/123/locations/global/"
    "workloadIdentityPools/poiesis/providers/cluster"
)
ACCOUNT = "filer@project.iam.gserviceaccount.com"


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    """The projected ServiceAccount token."""
    path = tmp_path / "token"
    path.write_text("k8s-jwt\n")
    return path


class Recorder:
    """httpx transport answering like STS and IAM Credentials, recording calls."""

    def __init__(self, sts_expires_in: int = 3600) -> None:
        self.requests: list[httpx.Request] = []
        self.sts_expires_in = sts_expires_in
        self.sts_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "sts.googleapis.com":
            if self.sts_status != 200:  # noqa: PLR2004
                return httpx.Response(self.sts_status, json={"error": "invalid_grant"})
            return httpx.Response(
                200,
                json={
                    "access_token": f"federated-{len(self.requests)}",
                    "token_type": "Bearer",
                    "expires_in": self.sts_expires_in,
                },
            )
        return httpx.Response(
            200,
            json={"accessToken": "sa-token", "expireTime": "2099-01-01T00:00:00Z"},
        )

    def provider(self, token_file: Path, account: str | None) -> GcsWorkloadIdentity:
        return GcsWorkloadIdentity(
            PROVIDER, str(token_file), account, transport=httpx.MockTransport(self)
        )


def test_token_is_exchanged_at_sts_for_the_pool_provider(token_file) -> None:
    """STS gets the token, the provider as audience, and answers a token."""
    recorder = Recorder()
    credential = asyncio.run(recorder.provider(token_file, None)())

    [request] = recorder.requests
    assert str(request.url) == "https://sts.googleapis.com/v1/token"
    assert json.loads(request.content) == {
        "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
        "audience": PROVIDER,
        "scope": "https://www.googleapis.com/auth/cloud-platform",
        "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
        "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
        "subjectToken": "k8s-jwt",
    }
    assert credential["token"] == "federated-1"
    expires_at = credential["expires_at"]
    assert expires_at is not None
    assert timedelta(minutes=59) < expires_at - datetime.now(UTC) <= timedelta(hours=1)


def test_service_account_is_impersonated_with_the_federated_token(token_file):
    """With a service account, its token is returned, not the federated one."""
    recorder = Recorder()
    credential = asyncio.run(recorder.provider(token_file, ACCOUNT)())

    sts, iam = recorder.requests
    assert sts.url.host == "sts.googleapis.com"
    assert str(iam.url) == (
        "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
        f"{ACCOUNT}:generateAccessToken"
    )
    assert iam.headers["Authorization"] == "Bearer federated-1"
    assert json.loads(iam.content) == {
        "scope": ["https://www.googleapis.com/auth/devstorage.read_write"]
    }
    assert credential == {
        "token": "sa-token",
        "expires_at": datetime(2099, 1, 1, tzinfo=UTC),
    }


def test_token_is_reused_until_it_nears_expiry(token_file) -> None:
    """A fresh token is reused; one about to expire is renewed from the file."""

    async def twice(provider: GcsWorkloadIdentity) -> list[str]:
        first = await provider()
        token_file.write_text("rotated-jwt")
        return [first["token"], (await provider())["token"]]

    fresh = Recorder(sts_expires_in=3600)
    assert asyncio.run(twice(fresh.provider(token_file, None))) == [
        "federated-1",
        "federated-1",
    ]
    assert len(fresh.requests) == 1

    expiring = Recorder(sts_expires_in=60)
    assert asyncio.run(twice(expiring.provider(token_file, None))) == [
        "federated-1",
        "federated-2",
    ]
    assert json.loads(expiring.requests[1].content)["subjectToken"] == "rotated-jwt"


def test_refused_exchange_names_the_status(token_file) -> None:
    """A refusal from STS is an error with its status and answer."""
    recorder = Recorder()
    recorder.sts_status = 400
    with pytest.raises(GcsIdentityError, match="returned 400: .*invalid_grant"):
        asyncio.run(recorder.provider(token_file, None)())


def test_token_audience_is_the_default_allowed_audience() -> None:
    """A provider made without --allowed-audiences accepts https:<name>."""
    assert token_audience(PROVIDER) == f"https:{PROVIDER}"


def test_no_provider_without_its_settings(monkeypatch) -> None:
    """Without the API's settings obstore uses its own chain (the key)."""
    monkeypatch.delenv(GCS_WORKLOAD_IDENTITY_PROVIDER_ENV, raising=False)
    monkeypatch.delenv(GCS_IDENTITY_TOKEN_FILE_ENV, raising=False)
    assert gcs_credential_provider() is None


# --- Through obstore -----------------------------------------------------------


class FakeGoogle(http.server.ThreadingHTTPServer):
    """STS, IAM Credentials and one GCS object, on 127.0.0.1."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.calls: list[tuple[str, str, str | None]] = []
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()

    def url(self, path: str = "") -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}{path}"


class _Handler(http.server.BaseHTTPRequestHandler):
    server: FakeGoogle

    def log_message(self, *_args: Any) -> None:
        pass

    def _reply(self, status: int, body: bytes, kind: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Last-Modified", "Sun, 22 Nov 2026 10:00:00 GMT")
        self.send_header("ETag", '"1"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.server.calls.append(("POST", self.path, self.headers["Authorization"]))
        if self.path == "/v1/token":
            answer = {"access_token": "federated", "expires_in": 3600}
        else:
            answer = {"accessToken": "sa-token", "expireTime": "2099-01-01T00:00:00Z"}
        self._reply(200, json.dumps(answer).encode())

    def do_GET(self) -> None:
        auth = self.headers["Authorization"]
        self.server.calls.append(("GET", unquote(self.path), auth))
        if auth != "Bearer sa-token":
            self._reply(401, b"no")
            return
        self._reply(200, b"from gcs\n", "application/octet-stream")


@pytest.fixture
def google() -> Iterator[FakeGoogle]:
    server = FakeGoogle()
    yield server
    server.shutdown()
    server.server_close()


def test_gs_input_is_read_with_the_impersonated_token(
    google, token_file, tmp_path, monkeypatch
) -> None:
    """tif's store asks the provider for a token and sends it to GCS."""
    monkeypatch.setattr(filer_strategy, "FILER_PVC_PATH", str(tmp_path))
    monkeypatch.setattr(gcs_identity, "STS_URL", google.url("/v1/token"))
    monkeypatch.setattr(gcs_identity, "IAM_CREDENTIALS_URL", google.url("/v1"))
    monkeypatch.setenv("GOOGLE_BASE_URL", google.url())
    monkeypatch.setenv(GCS_WORKLOAD_IDENTITY_PROVIDER_ENV, PROVIDER)
    monkeypatch.setenv(GCS_SERVICE_ACCOUNT_ENV, ACCOUNT)
    monkeypatch.setenv(GCS_IDENTITY_TOKEN_FILE_ENV, str(token_file))
    for name in ("GOOGLE_SERVICE_ACCOUNT_KEY", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(name, raising=False)

    url = "gs://bucket/in/reads.txt"
    store = make_store(ObjectUrl("gs", "bucket", "in/reads.txt"))
    strategy = ObjectStoreFilerStrategy(TesInput(url=url, path="/in/r"), store)
    target = tmp_path / "reads.txt"
    asyncio.run(strategy.download_input_file(str(target)))

    assert target.read_text() == "from gcs\n"
    assert google.calls == [
        ("POST", "/v1/token", None),
        (
            "POST",
            f"/v1/projects/-/serviceAccounts/{ACCOUNT}:generateAccessToken",
            "Bearer federated",
        ),
        ("GET", "/bucket/in/reads.txt", "Bearer sa-token"),
    ]
