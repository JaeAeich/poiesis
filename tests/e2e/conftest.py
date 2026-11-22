"""End-to-end tests against a deployed Poiesis.

The tests talk to a Poiesis deployed by ``tests/e2e/setup.sh`` (auth off)
at ``POIESIS_E2E_URL`` and use ``kubectl`` for what the API doesn't show:
Jobs and the object stores. See the "Testing" docs page.
"""

import os
import socket
import subprocess
import time
from collections.abc import Iterator

import httpx
import pytest
from e2e import CONTEXT, NAMESPACE, S3, URL, Azure, Gcs, Tes


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Refuse to run without a deployment rather than skip silently."""
    if items and not URL:
        raise pytest.UsageError("POIESIS_E2E_URL is not set; see tests/e2e/setup.sh")


@pytest.fixture(scope="session")
def tes() -> Iterator[Tes]:
    """Client for the TES API of the deployment under test."""
    with httpx.Client(base_url=f"{URL}/ga4gh/tes/v1", timeout=30) as client:
        yield Tes(client)


@pytest.fixture(scope="session")
def stores() -> Iterator[dict[str, S3 | Gcs | Azure]]:
    """Each object store by URL scheme, with the test bucket made.

    fake-gcs-server and Azurite are reached through ``kubectl
    port-forward`` unless ``POIESIS_E2E_GCS_URL`` / ``POIESIS_E2E_AZURE_URL``
    name them.
    """
    forwards: list[subprocess.Popen] = []

    def reach(env: str, service: str, local: int, remote: int) -> str:
        if url := os.environ.get(env):
            return url
        command = ["kubectl", "--context", CONTEXT, "-n", NAMESPACE]
        command += ["port-forward", f"svc/{service}", f"{local}:{remote}"]
        forwards.append(
            subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        )
        deadline = time.monotonic() + 30
        while True:
            try:
                socket.create_connection(("127.0.0.1", local), timeout=1).close()
            except OSError:
                assert time.monotonic() < deadline, f"no port-forward to {service}"
                time.sleep(0.5)
            else:
                return f"http://127.0.0.1:{local}"

    try:
        gcs = Gcs(reach("POIESIS_E2E_GCS_URL", "gcs", 14443, 4443))
        gcs.create_bucket()
        azure = Azure(reach("POIESIS_E2E_AZURE_URL", "azurite", 20000, 10000))
        azure.create_container()
        yield {"s3": S3(), "gs": gcs, "az": azure}
    finally:
        for forward in forwards:
            forward.terminate()
            forward.wait(timeout=10)
