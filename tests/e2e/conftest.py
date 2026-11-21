"""End-to-end tests against a deployed Poiesis.

The tests talk to a Poiesis deployed by ``tests/e2e/setup.sh`` (auth off)
at ``POIESIS_E2E_URL`` and use ``kubectl`` for what the API doesn't show:
Jobs and the S3 store. See the "Testing" docs page.
"""

from collections.abc import Iterator

import httpx
import pytest
from e2e import URL, Tes


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
