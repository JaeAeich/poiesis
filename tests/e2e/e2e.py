"""TES client and cluster helpers for the end-to-end tests (see conftest)."""

import base64
import hashlib
import hmac
import os
import subprocess
import time
from email.utils import formatdate
from typing import Any
from urllib.parse import quote

import httpx
import pytest

URL = os.environ.get("POIESIS_E2E_URL", "")
CONTEXT = os.environ.get("POIESIS_E2E_CONTEXT", "kind-poiesis-e2e")
NAMESPACE = os.environ.get("POIESIS_E2E_NAMESPACE", "poiesis")
BUCKET = "poiesis-e2e"
#: Bucket of the named store "second" (values.yaml), with its own keys.
SECOND_BUCKET = "poiesis-e2e-second"
TERMINAL = {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED"}
IMAGE = "busybox:1.36"
#: Azurite's development account and its published key (not a secret).
AZURE_ACCOUNT = "devstoreaccount1"
AZURE_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw=="
)


class Tes:
    """A small TES client: create, get, cancel, list, wait."""

    def __init__(self, client: httpx.Client) -> None:
        self.http = client

    def create(self, task: dict[str, Any]) -> str:
        """Create ``task`` and return its id; fail on anything but 200."""
        response = self.http.post("/tasks", json=task)
        assert response.status_code == 200, response.text
        return response.json()["id"]

    def get(self, task_id: str, view: str = "FULL") -> dict[str, Any]:
        """The task in ``view``."""
        response = self.http.get(f"/tasks/{task_id}", params={"view": view})
        assert response.status_code == 200, response.text
        return response.json()

    def cancel(self, task_id: str) -> None:
        """Cancel the task."""
        response = self.http.post(f"/tasks/{task_id}:cancel")
        assert response.status_code == 200, response.text

    def list(self, **params: Any) -> dict[str, Any]:
        """One page of tasks."""
        response = self.http.get("/tasks", params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def wait(
        self, task_id: str, states: set[str] = TERMINAL, timeout: float = 180
    ) -> dict[str, Any]:
        """Poll until the task is in one of ``states``; return it (FULL)."""
        deadline = time.monotonic() + timeout
        while True:
            task = self.get(task_id)
            if task["state"] in states:
                return task
            if task["state"] in TERMINAL or time.monotonic() > deadline:
                pytest.fail(
                    f"task {task_id} is {task['state']}, waited for {sorted(states)}"
                )
            time.sleep(1)

    def run(self, task: dict[str, Any], timeout: float = 180) -> dict[str, Any]:
        """Create ``task`` and wait until it ends."""
        return self.wait(self.create(task), timeout=timeout)


def kubectl(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run kubectl against the test cluster and namespace."""
    return subprocess.run(
        ["kubectl", "--context", CONTEXT, "-n", NAMESPACE, *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def s3_put(key: str, body: str, bucket: str = BUCKET) -> str:
    """Write ``body`` to ``key`` in ``bucket``; return its s3:// URL."""
    done = kubectl(
        "exec", "-i", "deploy/s3", "--", "curl", "-sf", "-T", "-",
        f"http://localhost:8888/buckets/{bucket}/{quote(key)}",
        stdin=body,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return f"s3://{bucket}/{key}"


def s3_get(key: str, bucket: str = BUCKET) -> str:
    """Body of ``key`` in ``bucket``."""
    done = kubectl(
        "exec", "deploy/s3", "--", "curl", "-sf",
        f"http://localhost:8888/buckets/{bucket}/{quote(key)}",
    )  # fmt: skip
    assert done.returncode == 0, f"s3://{bucket}/{key}: {done.stderr}"
    return done.stdout


class S3:
    """The test bucket on SeaweedFS, through its filer (kubectl exec)."""

    scheme = "s3"

    def url(self, key: str) -> str:
        """The s3:// URL of `key`."""
        return f"s3://{BUCKET}/{key}"

    def put(self, key: str, body: str) -> str:
        """Write `body` to `key`; return its URL."""
        return s3_put(key, body)

    def get(self, key: str) -> str:
        """Body of `key`."""
        return s3_get(key)

    def size(self, key: str) -> int:
        """Size of `key` in bytes."""
        done = kubectl(
            "exec", "deploy/s3", "--", "curl", "-sfI",
            f"http://localhost:8888/buckets/{BUCKET}/{quote(key)}",
        )  # fmt: skip
        assert done.returncode == 0, f"{self.url(key)}: {done.stderr}"
        for line in done.stdout.splitlines():
            name, _, value = line.partition(":")
            if name.lower() == "content-length":
                return int(value)
        raise AssertionError(f"{self.url(key)}: no Content-Length")


class Gcs:
    """The test bucket on fake-gcs-server at `base` (JSON API, no auth)."""

    scheme = "gs"

    def __init__(self, base: str) -> None:
        self.http = httpx.Client(base_url=base, timeout=30)

    def create_bucket(self) -> None:
        """Make the test bucket; one that exists is fine."""
        done = self.http.post("/storage/v1/b", json={"name": BUCKET})
        assert done.status_code in {200, 409}, done.text

    def url(self, key: str) -> str:
        """The gs:// URL of `key`."""
        return f"gs://{BUCKET}/{key}"

    def put(self, key: str, body: str) -> str:
        """Write `body` to `key`; return its URL."""
        done = self.http.post(
            f"/upload/storage/v1/b/{BUCKET}/o",
            params={"uploadType": "media", "name": key},
            content=body.encode(),
        )
        assert done.status_code == 200, done.text
        return self.url(key)

    def get(self, key: str) -> str:
        """Body of `key`."""
        done = self.http.get(
            f"/storage/v1/b/{BUCKET}/o/{quote(key, safe='')}", params={"alt": "media"}
        )
        assert done.status_code == 200, f"{self.url(key)}: {done.text}"
        return done.text

    def size(self, key: str) -> int:
        """Size of `key` in bytes."""
        done = self.http.get(f"/storage/v1/b/{BUCKET}/o/{quote(key, safe='')}")
        assert done.status_code == 200, f"{self.url(key)}: {done.text}"
        return int(done.json()["size"])


class Azure:
    """The test container on Azurite at `base`, signed with the account key."""

    scheme = "az"

    def __init__(self, base: str) -> None:
        self.http = httpx.Client(base_url=base, timeout=30)

    def _request(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """`method` on `path` below the account, with a SharedKey signature."""
        query = query or {}
        headers = {
            "x-ms-date": formatdate(usegmt=True),
            "x-ms-version": "2021-08-06",
            **(headers or {}),
        }
        path = quote(path)
        canonical_headers = "".join(
            f"{k}:{v}\n" for k, v in sorted(headers.items()) if k.startswith("x-ms-")
        )
        resource = f"/{AZURE_ACCOUNT}/{AZURE_ACCOUNT}/{path}" + "".join(
            f"\n{k}:{v}" for k, v in sorted(query.items())
        )
        length = str(len(body)) if body else ""
        fields = [method, "", "", length, "", "", "", "", "", "", "", ""]
        to_sign = "\n".join(fields) + "\n" + canonical_headers + resource
        signature = base64.b64encode(
            hmac.new(
                base64.b64decode(AZURE_KEY), to_sign.encode(), hashlib.sha256
            ).digest()
        ).decode()
        headers["Authorization"] = f"SharedKey {AZURE_ACCOUNT}:{signature}"
        return self.http.request(
            method,
            f"/{AZURE_ACCOUNT}/{path}",
            params=query,
            content=body,
            headers=headers,
        )

    def create_container(self) -> None:
        """Make the test container; one that exists is fine."""
        done = self._request("PUT", BUCKET, {"restype": "container"})
        assert done.status_code in {201, 409}, done.text

    def url(self, key: str) -> str:
        """The az:// URL of `key`."""
        return f"az://{BUCKET}/{key}"

    def put(self, key: str, body: str) -> str:
        """Write `body` to `key`; return its URL."""
        done = self._request(
            "PUT",
            f"{BUCKET}/{key}",
            body=body.encode(),
            headers={"x-ms-blob-type": "BlockBlob"},
        )
        assert done.status_code == 201, done.text
        return self.url(key)

    def get(self, key: str) -> str:
        """Body of `key`."""
        done = self._request("GET", f"{BUCKET}/{key}")
        assert done.status_code == 200, f"{self.url(key)}: {done.text}"
        return done.text

    def size(self, key: str) -> int:
        """Size of `key` in bytes."""
        done = self._request("HEAD", f"{BUCKET}/{key}")
        assert done.status_code == 200, f"{self.url(key)}: {done.status_code}"
        return int(done.headers["Content-Length"])
