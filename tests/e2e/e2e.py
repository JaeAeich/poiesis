"""TES client and cluster helpers for the end-to-end tests (see conftest)."""

import os
import subprocess
import time
from typing import Any

import httpx
import pytest

URL = os.environ.get("POIESIS_E2E_URL", "")
CONTEXT = os.environ.get("POIESIS_E2E_CONTEXT", "kind-poiesis-e2e")
NAMESPACE = os.environ.get("POIESIS_E2E_NAMESPACE", "poiesis")
BUCKET = "poiesis-e2e"
TERMINAL = {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED"}
IMAGE = "busybox:1.36"


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


def s3_put(key: str, body: str) -> str:
    """Write ``body`` to ``key`` in the test bucket; return its s3:// URL."""
    done = kubectl(
        "exec", "-i", "deploy/s3", "--", "curl", "-sf", "-T", "-",
        f"http://localhost:8888/buckets/{BUCKET}/{key}",
        stdin=body,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return f"s3://{BUCKET}/{key}"


def s3_get(key: str) -> str:
    """Body of ``key`` in the test bucket."""
    done = kubectl(
        "exec", "deploy/s3", "--", "curl", "-sf",
        f"http://localhost:8888/buckets/{BUCKET}/{key}",
    )  # fmt: skip
    assert done.returncode == 0, f"s3://{BUCKET}/{key}: {done.stderr}"
    return done.stdout
