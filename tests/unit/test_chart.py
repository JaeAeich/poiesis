"""Rendered Helm chart: NetworkPolicy, schema, rollout, TaskPod resources, metrics.

Runs `helm template` on the chart in `deployment/helm/poiesis` with the
`ci/` values files and checks the manifests (#168). Skipped without helm.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from prometheus_client import REGISTRY

from poiesis.api import metrics as api_metrics  # noqa: F401 (registers the metrics)
from poiesis.api.settings import AuthSettings, DatabaseSettings, Settings
from poiesis.core import tctl_metrics  # noqa: F401 (registers the metrics)
from poiesis.core.taskpod.config import SchedulingConfig

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
        ("taskpods.resources.maxCpu=1", "additional properties 'maxCpu'"),
        ("taskpods.backendParameters.allowed={VmSize}", "gpu_count"),
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


def test_system_resources_reach_the_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ConfigMap's JSON parses in Settings into the container resources."""
    configmap = next(d for d in render(LINT) if d["kind"] == "ConfigMap")["data"]
    for name in ("RECORDER", "FILER", "ACK"):
        monkeypatch.setenv(
            f"POIESIS_TASKPOD_{name}_RESOURCES",
            configmap[f"POIESIS_TASKPOD_{name}_RESOURCES"],
        )
    config = Settings(auth=AuthSettings(enabled=False)).runtime_config()
    assert config.filer_resources is not None
    assert config.filer_resources.limits == {"cpu": "1000m", "memory": "1Gi"}
    assert config.recorder_resources is not None
    assert config.recorder_resources.requests == {"cpu": "10m", "memory": "128Mi"}
    assert config.ack_resources is not None
    assert config.ack_resources.limits == {"cpu": "100m", "memory": "256Mi"}


def test_scheduling_reaches_the_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`taskpods` scheduling values parse in Settings (#170)."""
    configmap = next(d for d in render(FULL) if d["kind"] == "ConfigMap")["data"]
    monkeypatch.setenv(
        "POIESIS_TASKPOD_SCHEDULING", configmap["POIESIS_TASKPOD_SCHEDULING"]
    )
    scheduling = Settings(auth=AuthSettings(enabled=False)).runtime_config().scheduling
    assert scheduling.default_ram_gb == 2  # noqa: PLR2004
    assert scheduling.max_cpu_cores == 64  # noqa: PLR2004
    assert scheduling.cpu_limit is False
    assert scheduling.node_selector == {"poiesis.io/workload": "tasks"}
    assert scheduling.priority_class_name == "tasks-default"
    assert scheduling.runtime_class_name is None
    assert scheduling.preemptible is not None
    assert scheduling.preemptible.node_selector == {"cloud.google.com/gke-spot": "true"}
    assert scheduling.gpu_resource_name == "nvidia.com/gpu"
    assert scheduling.max_gpu_count == 4  # noqa: PLR2004
    assert scheduling.backend_parameters == {"gpu_count", "priority_class", "node_pool"}
    assert set(scheduling.node_pools) == {"highmem"}


def test_scheduling_defaults_change_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The chart's defaults are the builder's: no requests, no constraints."""
    configmap = next(d for d in render(LINT) if d["kind"] == "ConfigMap")["data"]
    monkeypatch.setenv(
        "POIESIS_TASKPOD_SCHEDULING", configmap["POIESIS_TASKPOD_SCHEDULING"]
    )
    scheduling = Settings(auth=AuthSettings(enabled=False)).runtime_config().scheduling
    assert scheduling == SchedulingConfig()


def test_system_resources_null_is_omitted() -> None:
    """`ack: null` renders no env, so ack gets no requests or limits."""
    configmap = next(d for d in render(FULL) if d["kind"] == "ConfigMap")["data"]
    assert "POIESIS_TASKPOD_ACK_RESOURCES" not in configmap
    assert json.loads(configmap["POIESIS_TASKPOD_FILER_RESOURCES"])["limits"] == {
        "cpu": 2,
        "memory": "2Gi",
    }


@pytest.mark.parametrize(
    ("sets", "expected"),
    [((), "json"), (("logging.format=text",), "text"), (("logging.format=",), None)],
)
def test_log_format_reaches_the_configmap(
    sets: tuple[str, ...], expected: str | None
) -> None:
    """`logging.format` is POIESIS_LOG_FORMAT; empty leaves it unset."""
    configmap = next(d for d in render(LINT, sets=sets) if d["kind"] == "ConfigMap")
    assert configmap["data"].get("POIESIS_LOG_FORMAT") == expected


def test_log_format_is_checked() -> None:
    """An unknown format fails `helm lint`."""
    result = helm("lint", str(CHART), "-f", LINT, "--set", "logging.format=yaml")
    assert result.returncode != 0


def test_database_pool_values_reach_the_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`database.pool` and `database.commandTimeoutSeconds` parse in Settings."""
    sets = (
        "database.pool.maxSize=25",
        "database.pool.acquireTimeoutSeconds=3",
        "database.commandTimeoutSeconds=60",
    )
    docs = render(LINT, sets=sets)
    configmap = next(d for d in docs if d["kind"] == "ConfigMap")["data"]
    for name, value in configmap.items():
        if name.startswith("POIESIS_DATABASE_"):
            monkeypatch.setenv(name, value)
    database = DatabaseSettings()
    assert (database.pool_min_size, database.pool_max_size) == (1, 25)
    assert database.acquire_timeout_seconds == 3  # noqa: PLR2004
    assert database.command_timeout_seconds == 60  # noqa: PLR2004


def storage_config(
    monkeypatch: pytest.MonkeyPatch, *sets: str
) -> tuple[dict[str, str], Any]:
    """The rendered ConfigMap's data, and the RuntimeConfig the API builds from it."""
    configmap = next(d for d in render(LINT, sets=sets) if d["kind"] == "ConfigMap")[
        "data"
    ]
    prefixes = ("POIESIS_S3_", "POIESIS_GCS_", "POIESIS_AZURE_")
    secrets = ("POIESIS_TASKPOD_S3_SECRET", "POIESIS_TASKPOD_GCS_SECRET")
    for name, value in configmap.items():
        if name.startswith(prefixes) or name in secrets:
            monkeypatch.setenv(name, value)
    return configmap, Settings(auth=AuthSettings(enabled=False)).runtime_config()


@pytest.fixture
def no_storage_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No object-store settings in the test's own environment."""
    for name in (
        "AWS_ACCESS_KEY_ID",
        "POIESIS_TASKPOD_S3_SECRET",
        "POIESIS_S3_ENABLED",
        "POIESIS_S3_ROLE_ARN",
        "POIESIS_GCS_ENABLED",
        "POIESIS_GCS_ENDPOINT",
        "POIESIS_GCS_WORKLOAD_IDENTITY_PROVIDER",
        "POIESIS_GCS_SERVICE_ACCOUNT",
        "POIESIS_TASKPOD_GCS_SECRET",
        "POIESIS_AZURE_ENABLED",
        "POIESIS_AZURE_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("no_storage_env")
def test_s3_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Secret, no switch: no S3 settings, and S3 is off."""
    configmap, config = storage_config(monkeypatch)
    assert not [n for n in configmap if n.startswith("POIESIS_S3_")]
    assert not config.s3_configured


@pytest.mark.usefixtures("no_storage_env")
def test_existing_s3_secret_keeps_s3_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Installs that set only `s3.existingSecret` work as before."""
    configmap, config = storage_config(monkeypatch, "s3.existingSecret=poiesis-s3")
    assert configmap["POIESIS_TASKPOD_S3_SECRET"] == "poiesis-s3"
    assert config.s3_configured
    assert not config.filer_identity_audiences


@pytest.mark.usefixtures("no_storage_env")
def test_s3_role_reaches_the_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """`s3.roleArn` turns S3 on with a token for STS, and no Secret."""
    role = "arn:aws:iam::123456789012:role/poiesis"
    configmap, config = storage_config(monkeypatch, f"s3.roleArn={role}")
    assert "POIESIS_TASKPOD_S3_SECRET" not in configmap
    assert config.s3_configured
    assert config.filer_identity_audiences == {"aws": "sts.amazonaws.com"}


@pytest.mark.usefixtures("no_storage_env")
def test_gcs_workload_identity_reaches_the_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`gcs.workloadIdentityProvider` gives a token for the provider, no Secret."""
    provider = (
        "//iam.googleapis.com/projects/1/locations/global/"
        "workloadIdentityPools/pool/providers/k8s"
    )
    configmap, config = storage_config(
        monkeypatch,
        "gcs.enabled=true",
        f"gcs.workloadIdentityProvider={provider}",
        "gcs.serviceAccount=filer@p.iam.gserviceaccount.com",
        "gcs.endpoint=https://storage.example",
    )
    assert "POIESIS_TASKPOD_GCS_SECRET" not in configmap
    assert config.gcs_configured
    assert config.filer_identity_audiences == {"gcp": f"https:{provider}"}
    env = {e.name: e.value for e in config.filer_env}
    assert env["POIESIS_GCS_SERVICE_ACCOUNT"] == "filer@p.iam.gserviceaccount.com"
    assert env["GOOGLE_BASE_URL"] == "https://storage.example"


@pytest.mark.usefixtures("no_storage_env")
def test_azure_endpoint_reaches_the_filers(monkeypatch: pytest.MonkeyPatch) -> None:
    """`azure.endpoint` becomes the filers' AZURE_STORAGE_ENDPOINT."""
    _, config = storage_config(
        monkeypatch,
        "azure.enabled=true",
        "azure.accountName=acct",
        "azure.endpoint=http://azurite:10000/acct",
    )
    env = {e.name: e.value for e in config.filer_env}
    assert env["AZURE_STORAGE_ENDPOINT"] == "http://azurite:10000/acct"


@pytest.mark.parametrize(
    ("sets", "error"),
    [
        (("gcs.enabled=true",), "gcs.enabled needs one of gcs.existingSecret"),
        (
            (
                "gcs.enabled=true",
                "gcs.existingSecret=k",
                "gcs.workloadIdentityProvider=//iam.googleapis.com/p",
            ),
            "gcs.enabled needs one of",
        ),
        (
            ("gcs.enabled=true", "gcs.existingSecret=k", "gcs.serviceAccount=a@b"),
            "gcs.serviceAccount needs gcs.workloadIdentityProvider",
        ),
        (("gcs.workloadIdentityProvider=projects/1",), "does not match pattern"),
        (("gcs.endpoint=storage.example",), "does not match pattern"),
        (("azure.endpoint=blob.example",), "does not match pattern"),
        (("azure.enabled=true",), "azure.enabled needs azure.accountName"),
        (
            ("azure.enabled=true", "azure.accountName=a", "azure.clientId=c"),
            "set together",
        ),
        (("s3.kmsKeyId=k",), "s3.kmsKeyId needs s3.serverSideEncryption"),
        (("s3.serverSideEncryption=aes",), "value must be one of"),
    ],
)
def test_unusable_storage_values_fail_the_install(
    sets: tuple[str, ...], error: str
) -> None:
    """Values tif/tof couldn't use fail `helm template`, with the reason."""
    args = ["template", "t", str(CHART), "-f", LINT]
    for item in sets:
        args += ["--set", item]
    result = helm(*args)
    assert result.returncode != 0
    assert error in result.stderr


def ftp_drs_config(monkeypatch: pytest.MonkeyPatch, *sets: str) -> Any:
    """The RuntimeConfig the API builds from the rendered FTP and DRS settings."""
    configmap = next(d for d in render(LINT, sets=sets) if d["kind"] == "ConfigMap")[
        "data"
    ]
    for name, value in configmap.items():
        if name.startswith(("POIESIS_FTP_", "POIESIS_DRS_", "POIESIS_TASKPOD_DRS_")):
            monkeypatch.setenv(name, value)
    return Settings(auth=AuthSettings(enabled=False)).runtime_config()


def test_ftp_on_and_drs_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults: FTP on, DRS off, no DRS token."""
    config = ftp_drs_config(monkeypatch)
    assert config.ftp_enabled
    assert not config.drs_enabled
    assert config.drs_secret is None


def test_ftp_and_drs_values_reach_the_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`taskpods.ftp` and `taskpods.drs` values reach the RuntimeConfig."""
    config = ftp_drs_config(
        monkeypatch,
        "taskpods.ftp.enabled=false",
        "taskpods.drs.enabled=true",
        "taskpods.drs.allowedHosts={drs.example.org,Other.org}",
        "taskpods.drs.existingSecret=poiesis-drs",
    )
    assert not config.ftp_enabled
    assert config.drs_enabled
    assert config.drs_allowed_hosts == ("drs.example.org", "other.org")
    assert config.drs_secret == "poiesis-drs"


def containers(docs: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """The first container of Deployment `name`."""
    return find(docs, "Deployment", name)["spec"]["template"]["spec"]["containers"][0]


def ingress_ports(policy: dict[str, Any]) -> dict[int, list[Any] | None]:
    """Ingress TCP port → the rule's `from` peers (None: any source)."""
    return {
        port["port"]: rule.get("from")
        for rule in policy["spec"].get("ingress", [])
        for port in rule["ports"]
    }


def test_metrics_are_on_by_default_on_their_own_port() -> None:
    """Port 9090 on both Deployments and Services; the API Service is untouched."""
    docs = render(LINT)
    configmap = next(d for d in docs if d["kind"] == "ConfigMap")["data"]
    assert configmap["POIESIS_METRICS_PORT"] == "9090"
    for name in ("api", "tctl"):
        ports = {p["name"]: p["containerPort"] for p in containers(docs, name)["ports"]}
        assert ports["metrics"] == 9090  # noqa: PLR2004
        service = find(docs, "Service", f"{name}-metrics")
        assert service["spec"]["ports"] == [
            {
                "name": "metrics",
                "port": 9090,
                "targetPort": "metrics",
                "protocol": "TCP",
            }
        ]
        assert service["spec"]["selector"]["app.kubernetes.io/component"] == name
        annotations = find(docs, "Deployment", name)["spec"]["template"]["metadata"][
            "annotations"
        ]
        assert not {k for k in annotations if k.split("/")[0] == "prometheus.io"}
    # The Ingress routes to the API Service, which has no metrics port.
    assert [p["name"] for p in find(docs, "Service", "api")["spec"]["ports"]] == [
        "http"
    ]
    kinds = {d["kind"] for d in docs}
    assert "ServiceMonitor" not in kinds
    assert not any(d["metadata"]["name"].endswith("-dashboard") for d in docs)


def test_metrics_disabled_renders_none_of_it() -> None:
    docs = render(LINT, sets=("metrics.enabled=false", "networkPolicy.enabled=true"))
    configmap = next(d for d in docs if d["kind"] == "ConfigMap")["data"]
    assert "POIESIS_METRICS_PORT" not in configmap
    assert not any(d["metadata"]["name"].endswith("-metrics") for d in docs)
    assert "ports" not in containers(docs, "tctl")
    assert [p["name"] for p in containers(docs, "api")["ports"]] == ["http"]
    tctl_policy = find(docs, "NetworkPolicy", "tctl")
    assert tctl_policy["spec"]["policyTypes"] == ["Egress"]
    api_policy = find(docs, "NetworkPolicy", "api")
    assert 9090 not in ingress_ports(api_policy)  # noqa: PLR2004


def test_service_monitor_scrape_annotations_and_network_policy() -> None:
    """full-values: port 9100, a ServiceMonitor, annotations, metricsFrom."""
    docs = render(FULL)
    monitor = next(d for d in docs if d["kind"] == "ServiceMonitor")
    assert monitor["metadata"]["labels"]["release"] == "kube-prometheus-stack"
    assert monitor["spec"]["selector"]["matchLabels"]["poiesis.io/metrics"] == "true"
    assert monitor["spec"]["endpoints"] == [
        {
            "port": "metrics",
            "path": "/metrics",
            "interval": "15s",
            "scrapeTimeout": "10s",
        }
    ]
    selected = [
        d["metadata"]["name"]
        for d in docs
        if d["kind"] == "Service"
        and all(
            d["metadata"]["labels"].get(k) == v
            for k, v in monitor["spec"]["selector"]["matchLabels"].items()
        )
    ]
    assert sorted(selected) == ["t-poiesis-api-metrics", "t-poiesis-tctl-metrics"]
    monitoring = [
        {
            "namespaceSelector": {
                "matchLabels": {"kubernetes.io/metadata.name": "monitoring"}
            }
        }
    ]
    for name in ("api", "tctl"):
        annotations = find(docs, "Deployment", name)["spec"]["template"]["metadata"][
            "annotations"
        ]
        assert annotations["prometheus.io/scrape"] == "true"
        assert annotations["prometheus.io/port"] == "9100"
        assert annotations["prometheus.io/path"] == "/metrics"
        assert ingress_ports(find(docs, "NetworkPolicy", name))[9100] == monitoring
    assert find(docs, "NetworkPolicy", "tctl")["spec"]["policyTypes"] == [
        "Ingress",
        "Egress",
    ]
    # The TES API's own port keeps its peers.
    assert ingress_ports(find(docs, "NetworkPolicy", "api"))[8000] != monitoring


def test_metrics_from_empty_allows_any_source() -> None:
    docs = render(LINT, sets=("networkPolicy.enabled=true",))
    for name in ("api", "tctl"):
        assert ingress_ports(find(docs, "NetworkPolicy", name))[9090] is None


def test_dashboard_configmap_holds_the_dashboard() -> None:
    docs = render(LINT, sets=("metrics.dashboard.enabled=true",))
    configmap = find(docs, "ConfigMap", "dashboard")
    assert configmap["metadata"]["labels"]["grafana_dashboard"] == "1"
    dashboard = json.loads(configmap["data"]["poiesis.json"])
    assert dashboard == json.loads((CHART / "dashboards" / "poiesis.json").read_text())


def test_dashboard_queries_name_known_metrics() -> None:
    """Every metric a dashboard panel queries is one Poiesis exports."""
    suffixes = {"counter": ("_total",), "histogram": ("_bucket", "_count", "_sum")}
    exported = {
        family.name + suffix
        for family in REGISTRY.collect()
        for suffix in suffixes.get(family.type, ("",))
    }
    dashboard = json.loads((CHART / "dashboards" / "poiesis.json").read_text())
    queried = {
        name
        for panel in dashboard["panels"]
        for target in panel["targets"]
        for name in re.findall(r"\bpoiesis_[a-z_]+", target["expr"])
    }
    assert queried
    assert queried <= exported, queried - exported
