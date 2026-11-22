"""The API and tctl answer on their metrics port (#175), through the Services."""

import pytest
from e2e import NAMESPACE, kubectl


@pytest.mark.parametrize(
    ("component", "metric"),
    [
        ("api", "poiesis_http_requests_total"),
        ("tctl", "poiesis_tctl_is_leader"),
    ],
)
def test_metrics_endpoint_answers(component: str, metric: str) -> None:
    """GET /metrics on `<release>-<component>-metrics`, via the API server proxy."""
    done = kubectl(
        "get",
        "--raw",
        f"/api/v1/namespaces/{NAMESPACE}/services/"
        f"poiesis-{component}-metrics:metrics/proxy/metrics",
    )
    assert done.returncode == 0, done.stderr
    assert metric in done.stdout
