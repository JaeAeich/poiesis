"""Rendered Helm chart: NetworkPolicy, values schema, rollout, TaskPod resources.

Runs `helm template` on the chart in `deployment/helm/poiesis` with the
`ci/` values files and checks the manifests (#168). Skipped without helm.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

CHART = Path(__file__).parents[2] / "deployment" / "helm" / "poiesis"
LINT = str(CHART / "ci" / "lint-values.yaml")
FULL = str(CHART / "ci" / "full-values.yaml")
HELM = shutil.which("helm")

pytestmark = pytest.mark.skipif(HELM is None, reason="helm is not installed")


def helm(*args: str) -> subprocess.CompletedProcess[str]:
    """Run helm on the chart; never raises on a non-zero exit."""
    assert HELM is not None
    return subprocess.run(  # noqa: S603
        [HELM, *args], capture_output=True, text=True, check=False
    )


def render(*values: str, sets: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Manifests `helm template` renders with the given values files."""
    args = ["template", "t", str(CHART)]
    for path in values:
        args += ["-f", path]
    for item in sets:
        args += ["--set", item]
    result = helm(*args)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    """The manifest of `kind` named `t-poiesis-<name>`."""
    for doc in docs:
        if doc["kind"] == kind and doc["metadata"]["name"] == f"t-poiesis-{name}":
            return doc
    raise AssertionError(f"no {kind} t-poiesis-{name}")


def egress_ports(policy: dict[str, Any]) -> dict[int, list[Any] | None]:
    """Egress TCP port → the rule's `to` peers (None: any destination)."""
    ports: dict[int, list[Any] | None] = {}
    for rule in policy["spec"]["egress"]:
        for port in rule["ports"]:
            if port["protocol"] == "TCP":
                ports[port["port"]] = rule.get("to")
    return ports


@pytest.mark.parametrize("name", ["api", "tctl"])
def test_default_policy_allows_postgres_and_https(name: str) -> None:
    """Postgres on 5432 and 443/6443 to any address, for the API and tctl."""
    policy = find(render(LINT), "NetworkPolicy", name)
    ports = egress_ports(policy)
    assert ports[5432] is None
    assert ports[443] is None
    assert ports[6443] is None


def test_database_egress_and_ingress_from_are_rendered() -> None:
    """Port and peers of databaseEgress, ingressFrom and extraEgress."""
    docs = render(FULL)
    api = find(docs, "NetworkPolicy", "api")
    ports = egress_ports(api)
    assert ports[6432] == [{"ipBlock": {"cidr": "10.0.12.0/24"}}]
    assert ports[9000] == [{"ipBlock": {"cidr": "192.0.2.10/32"}}]
    assert 5432 not in ports  # noqa: PLR2004
    peers = api["spec"]["ingress"][0]["from"]
    assert {
        "namespaceSelector": {
            "matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}
        }
    } in peers
    assert egress_ports(find(docs, "NetworkPolicy", "tctl"))[6432] is not None


def test_database_egress_null_drops_the_rule() -> None:
    """databaseEgress: null leaves Postgres to extraEgress."""
    policy = find(
        render(LINT, sets=("networkPolicy.databaseEgress=null",)),
        "NetworkPolicy",
        "api",
    )
    assert 5432 not in egress_ports(policy)  # noqa: PLR2004


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ("taskpod.namespace=x", "additional properties 'taskpod' not allowed"),
        ("api.resources.request.cpu=1", "additional properties 'request'"),
    ],
)
def test_schema_refuses_unknown_keys(override: str, error: str) -> None:
    """A typo in a key fails `helm lint` instead of being ignored."""
    result = helm("lint", str(CHART), "-f", LINT, "--set", override)
    assert result.returncode != 0
    assert error in result.stdout + result.stderr


def test_schema_accepts_global() -> None:
    """Helm passes `global` to a chart used as a dependency."""
    assert render(LINT, sets=("global.imageRegistry=example.org",))


def api_pod(*values: str, sets: tuple[str, ...] = ()) -> dict[str, Any]:
    """Pod spec of the API Deployment."""
    return find(render(*values, sets=sets), "Deployment", "api")["spec"]["template"][
        "spec"
    ]


def test_api_shutdown_defaults() -> None:
    """A preStop sleep and a grace period covering gunicorn's 30 s drain."""
    pod = api_pod(LINT)
    container = pod["containers"][0]
    sleep = int(container["lifecycle"]["preStop"]["exec"]["command"][1])
    assert sleep == 5  # noqa: PLR2004
    assert pod["terminationGracePeriodSeconds"] >= sleep + 30
    assert container["readinessProbe"]["failureThreshold"] == 3  # noqa: PLR2004
    assert container["livenessProbe"]["failureThreshold"] == 3  # noqa: PLR2004
    assert "topologySpreadConstraints" not in pod


def test_api_rollout_values_are_rendered() -> None:
    """Probe thresholds, shutdown and topology spread from values."""
    pod = api_pod(FULL)
    container = pod["containers"][0]
    assert container["readinessProbe"]["failureThreshold"] == 2  # noqa: PLR2004
    assert container["livenessProbe"]["failureThreshold"] == 6  # noqa: PLR2004
    assert container["lifecycle"]["preStop"]["exec"]["command"] == ["sleep", "10"]
    assert pod["terminationGracePeriodSeconds"] == 45  # noqa: PLR2004
    zone, host = pod["topologySpreadConstraints"]
    # Without a labelSelector, the API Pods' own labels.
    assert zone["labelSelector"]["matchLabels"] == {
        "app.kubernetes.io/name": "poiesis",
        "app.kubernetes.io/instance": "t",
        "app.kubernetes.io/component": "api",
    }
    assert host["labelSelector"]["matchLabels"] == {
        "app.kubernetes.io/component": "api"
    }


def test_prestop_sleep_zero_drops_the_hook() -> None:
    """preStopSleepSeconds: 0 renders no lifecycle hook."""
    pod = api_pod(LINT, sets=("api.preStopSleepSeconds=0",))
    assert "lifecycle" not in pod["containers"][0]
