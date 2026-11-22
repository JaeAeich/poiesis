"""Which object stores a deployment offers, and how TIF/TOF reach them (#162).

S3 is on with ``POIESIS_S3_ENABLED`` (workload identity or instance
credentials need no key) as well as with keys. `gs://` and `az://` have
their own switches. With a role (AWS) or client and tenant IDs (Azure),
the TaskPod gets a ServiceAccount token for that provider mounted into TIF
and TOF only, never into an executor.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from kubernetes.client import ApiClient, V1Container
from pydantic import ValidationError

from poiesis.api.app import create_app
from poiesis.api.settings import AuthSettings, Settings, StorageSettings
from poiesis.api.tes.models import TesExecutor, TesInput, TesOutput, TesTask
from poiesis.core.constants import IDENTITY_TOKEN_DIR
from poiesis.core.taskpod import build_taskpod_job

ROLE = "arn:aws:iam::123456789012:role/poiesis-filer"
AZURE_CLIENT = "00000000-0000-0000-0000-00000000c1d"
AZURE_TENANT = "00000000-0000-0000-0000-0000000007e7"
GCS_PROVIDER = (
    "//iam.googleapis.com/projects/123/locations/global/"
    "workloadIdentityPools/poiesis/providers/cluster"
)
PROVIDER_ENV = "POIESIS_GCS_WORKLOAD_IDENTITY_PROVIDER"

#: Every variable these tests read; cleared before each.
STORAGE_ENV = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_ENDPOINT_URL",
    "AWS_REGION",
    "POIESIS_TASKPOD_S3_SECRET",
    "POIESIS_TASKPOD_EXTRA_ENV",
    "POIESIS_S3_ENABLED",
    "POIESIS_S3_ROLE_ARN",
    "POIESIS_S3_VIRTUAL_HOSTED_STYLE",
    "POIESIS_S3_SERVER_SIDE_ENCRYPTION",
    "POIESIS_S3_SSE_KMS_KEY_ID",
    "POIESIS_S3_REQUESTER_PAYS",
    "POIESIS_GCS_ENABLED",
    "POIESIS_TASKPOD_GCS_SECRET",
    "POIESIS_GCS_ENDPOINT",
    "POIESIS_GCS_WORKLOAD_IDENTITY_PROVIDER",
    "POIESIS_GCS_SERVICE_ACCOUNT",
    "POIESIS_AZURE_ENABLED",
    "POIESIS_AZURE_ENDPOINT",
    "POIESIS_AZURE_ACCOUNT_NAME",
    "POIESIS_AZURE_CLIENT_ID",
    "POIESIS_AZURE_TENANT_ID",
    "POIESIS_TASKPOD_AZURE_SECRET",
    "POIESIS_FILE_URL_ROOTS",
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in STORAGE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POIESIS_TASKPOD_DATABASE_SECRET", "task-db")


def task(*urls: str) -> TesTask:
    """A task with one input and one output at each of `urls`."""
    return TesTask(
        id="t1",
        inputs=[TesInput(path=f"/in/{n}", url=u) for n, u in enumerate(urls)],
        outputs=[TesOutput(path=f"/out/{n}", url=u) for n, u in enumerate(urls)],
        executors=[TesExecutor(image="busybox:1.36", command=["true"])],
    )


def pod(*urls: str) -> dict:
    """The TaskPod spec built from the current environment, as plain JSON."""
    config = Settings(auth=AuthSettings(enabled=False)).runtime_config()
    _, job = build_taskpod_job(task(*urls), config)
    return ApiClient().sanitize_for_serialization(job.spec.template.spec)


def containers(spec: dict) -> dict[str, dict]:
    """The Pod's containers by name."""
    return {c["name"]: c for c in [*spec["initContainers"], *spec["containers"]]}


def env(container: dict) -> dict[str, dict]:
    """A container's env entries by name."""
    return {e["name"]: e for e in container.get("env", [])}


def mounts(container: dict) -> set[str]:
    """Mount paths of a container."""
    return {m["mountPath"] for m in container.get("volumeMounts", [])}


# --- S3 ------------------------------------------------------------------------


def test_s3_switch_turns_s3_on_without_keys(monkeypatch):
    """Instance credentials (IMDS) or a webhook-injected identity: no keys."""
    monkeypatch.setenv("POIESIS_S3_ENABLED", "true")
    spec = pod("s3://bucket/key")
    for name, container in containers(spec).items():
        assert "AWS_ACCESS_KEY_ID" not in env(container), name
    assert not [v for v in spec["volumes"] if v["name"].endswith("-identity-token")]


def test_s3_switch_refuses_a_typo(monkeypatch):
    """A misspelled value is an error at startup, not off."""
    monkeypatch.setenv("POIESIS_S3_ENABLED", "yes please")
    with pytest.raises(ValueError, match="POIESIS_S3_ENABLED"):
        StorageSettings()


def test_role_gives_tif_and_tof_a_web_identity_token(monkeypatch):
    """IRSA without the webhook: the token is for STS and reaches the filers only."""
    monkeypatch.setenv("POIESIS_S3_ROLE_ARN", ROLE)
    spec = pod("s3://bucket/key")
    token_dir = f"{IDENTITY_TOKEN_DIR}/aws"
    [volume] = [v for v in spec["volumes"] if v["name"] == "aws-identity-token"]
    [source] = volume["projected"]["sources"]
    assert source["serviceAccountToken"]["audience"] == "sts.amazonaws.com"
    assert source["serviceAccountToken"]["path"] == "token"
    found = containers(spec)
    for name in ("tif", "tof"):
        assert token_dir in mounts(found[name])
        assert env(found[name])["AWS_ROLE_ARN"]["value"] == ROLE
        assert env(found[name])["AWS_WEB_IDENTITY_TOKEN_FILE"]["value"] == (
            f"{token_dir}/token"
        )
    others = [n for n in found if n not in ("tif", "tof")]
    assert "trec" in others
    assert any(n.startswith("exec") for n in others)
    for name in others:
        assert token_dir not in mounts(found[name]), name
        assert "AWS_ROLE_ARN" not in env(found[name]), name
    assert spec["automountServiceAccountToken"] is False


def test_s3_options_reach_the_filers_only(monkeypatch):
    """Addressing style, SSE and requester-pays are set on TIF/TOF."""
    monkeypatch.setenv("POIESIS_S3_ENABLED", "true")
    monkeypatch.setenv("POIESIS_S3_VIRTUAL_HOSTED_STYLE", "true")
    monkeypatch.setenv("POIESIS_S3_SERVER_SIDE_ENCRYPTION", "aws:kms")
    monkeypatch.setenv("POIESIS_S3_SSE_KMS_KEY_ID", "alias/poiesis")
    monkeypatch.setenv("POIESIS_S3_REQUESTER_PAYS", "true")
    found = containers(pod("s3://bucket/key"))
    expected = {
        "POIESIS_S3_VIRTUAL_HOSTED_STYLE": "true",
        "POIESIS_S3_SERVER_SIDE_ENCRYPTION": "aws:kms",
        "POIESIS_S3_SSE_KMS_KEY_ID": "alias/poiesis",
        "POIESIS_S3_REQUESTER_PAYS": "true",
    }
    for name in ("tif", "tof"):
        assert {k: env(found[name])[k]["value"] for k in expected} == expected
    assert not set(expected) & set(env(found["trec"]))


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ({"POIESIS_S3_SERVER_SIDE_ENCRYPTION": "aes256"}, "must be one of"),
        ({"POIESIS_S3_SSE_KMS_KEY_ID": "k"}, "needs POIESIS_S3_SERVER_SIDE"),
        (
            {
                "POIESIS_S3_SERVER_SIDE_ENCRYPTION": "AES256",
                "POIESIS_S3_SSE_KMS_KEY_ID": "k",
            },
            "needs POIESIS_S3_SERVER_SIDE",
        ),
    ],
)
def test_bad_sse_settings_are_refused(monkeypatch, values, match):
    """An SSE mode obstore doesn't take, or a KMS key without KMS."""
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError, match=match):
        StorageSettings()


# --- Google Cloud Storage ----------------------------------------------------


def test_gcs_needs_a_key_secret_or_a_pool_provider(monkeypatch):
    """Without either it would use the metadata server, which executors reach."""
    monkeypatch.setenv("POIESIS_GCS_ENABLED", "true")
    with pytest.raises(ValidationError, match="metadata server"):
        StorageSettings()


@pytest.mark.parametrize(
    ("values", "match"),
    [
        (
            {"POIESIS_TASKPOD_GCS_SECRET": "k", PROVIDER_ENV: GCS_PROVIDER},
            "not both",
        ),
        ({PROVIDER_ENV: "projects/1/providers/x"}, "full name"),
        (
            {"POIESIS_TASKPOD_GCS_SECRET": "k", "POIESIS_GCS_SERVICE_ACCOUNT": "a@b"},
            "POIESIS_GCS_SERVICE_ACCOUNT needs",
        ),
        ({"POIESIS_GCS_ENDPOINT": "storage.example"}, "http"),
        ({"POIESIS_AZURE_ENDPOINT": "blob.example"}, "http"),
    ],
)
def test_bad_gcs_and_azure_settings_are_refused(monkeypatch, values, match):
    """Settings tif/tof could not use stop the API at startup."""
    monkeypatch.setenv("POIESIS_GCS_ENABLED", "true")
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    if "POIESIS_TASKPOD_GCS_SECRET" not in values and PROVIDER_ENV not in values:
        monkeypatch.setenv("POIESIS_TASKPOD_GCS_SECRET", "k")
    with pytest.raises(ValidationError, match=match):
        StorageSettings()


def test_gcs_workload_identity_token_reaches_the_filers_only(monkeypatch):
    """The pool provider's token and settings are on tif/tof, no key."""
    monkeypatch.setenv("POIESIS_GCS_ENABLED", "true")
    monkeypatch.setenv(PROVIDER_ENV, GCS_PROVIDER)
    monkeypatch.setenv("POIESIS_GCS_SERVICE_ACCOUNT", "filer@p.iam.gserviceaccount.com")
    spec = pod("gs://bucket/key")
    [volume] = [v for v in spec["volumes"] if v["name"] == "gcp-identity-token"]
    [source] = volume["projected"]["sources"]
    assert source["serviceAccountToken"]["audience"] == f"https:{GCS_PROVIDER}"
    found = containers(spec)
    token_dir = f"{IDENTITY_TOKEN_DIR}/gcp"
    for name in ("tif", "tof"):
        values = {k: v.get("value") for k, v in env(found[name]).items()}
        assert values[PROVIDER_ENV] == GCS_PROVIDER
        assert values["POIESIS_GCS_SERVICE_ACCOUNT"] == (
            "filer@p.iam.gserviceaccount.com"
        )
        assert values["POIESIS_GCS_IDENTITY_TOKEN_FILE"] == f"{token_dir}/token"
        assert "GOOGLE_SERVICE_ACCOUNT_KEY" not in values
        assert token_dir in mounts(found[name])
    for name, container in found.items():
        if name not in ("tif", "tof"):
            assert token_dir not in mounts(container), name
            assert PROVIDER_ENV not in env(container), name


def test_gcs_endpoint_reaches_the_filers_only(monkeypatch):
    """`gcs.endpoint` is the filers' GOOGLE_BASE_URL."""
    monkeypatch.setenv("POIESIS_GCS_ENABLED", "true")
    monkeypatch.setenv("POIESIS_TASKPOD_GCS_SECRET", "poiesis-gcs")
    monkeypatch.setenv("POIESIS_GCS_ENDPOINT", "http://gcs:4443")
    found = containers(pod("gs://bucket/key"))
    for name, container in found.items():
        value = env(container).get("GOOGLE_BASE_URL", {}).get("value")
        assert value == ("http://gcs:4443" if name in ("tif", "tof") else None), name


def test_gcs_key_is_a_secret_reference_on_the_filers(monkeypatch):
    """The key reaches TIF/TOF from the Secret, never as a value."""
    monkeypatch.setenv("POIESIS_GCS_ENABLED", "true")
    monkeypatch.setenv("POIESIS_TASKPOD_GCS_SECRET", "poiesis-gcs")
    found = containers(pod("gs://bucket/key"))
    for name in ("tif", "tof"):
        ref = env(found[name])["GOOGLE_SERVICE_ACCOUNT_KEY"]["valueFrom"]
        assert ref["secretKeyRef"] == {
            "name": "poiesis-gcs",
            "key": "GOOGLE_SERVICE_ACCOUNT_KEY",
        }
    for name, container in found.items():
        if name not in ("tif", "tof"):
            assert "GOOGLE_SERVICE_ACCOUNT_KEY" not in env(container), name


# --- Azure Blob Storage ------------------------------------------------------


def test_azure_needs_an_account(monkeypatch):
    """The account is part of every blob URL."""
    monkeypatch.setenv("POIESIS_AZURE_ENABLED", "true")
    with pytest.raises(ValidationError, match="POIESIS_AZURE_ACCOUNT_NAME"):
        StorageSettings()


def test_azure_client_and_tenant_go_together(monkeypatch):
    """A client ID alone can't be exchanged."""
    monkeypatch.setenv("POIESIS_AZURE_CLIENT_ID", AZURE_CLIENT)
    with pytest.raises(ValidationError, match="set together"):
        StorageSettings()


def test_azure_workload_identity_token_reaches_the_filers_only(monkeypatch):
    """The token is for Entra ID's exchange audience; executors don't get it."""
    monkeypatch.setenv("POIESIS_AZURE_ENABLED", "true")
    monkeypatch.setenv("POIESIS_AZURE_ACCOUNT_NAME", "poiesisdata")
    monkeypatch.setenv("POIESIS_AZURE_CLIENT_ID", AZURE_CLIENT)
    monkeypatch.setenv("POIESIS_AZURE_TENANT_ID", AZURE_TENANT)
    spec = pod("az://container/blob")
    [volume] = [v for v in spec["volumes"] if v["name"] == "azure-identity-token"]
    [source] = volume["projected"]["sources"]
    assert source["serviceAccountToken"]["audience"] == "api://AzureADTokenExchange"
    found = containers(spec)
    token_dir = f"{IDENTITY_TOKEN_DIR}/azure"
    for name in ("tif", "tof"):
        values = {k: v.get("value") for k, v in env(found[name]).items()}
        assert values["AZURE_STORAGE_ACCOUNT_NAME"] == "poiesisdata"
        assert values["AZURE_CLIENT_ID"] == AZURE_CLIENT
        assert values["AZURE_TENANT_ID"] == AZURE_TENANT
        assert values["AZURE_FEDERATED_TOKEN_FILE"] == f"{token_dir}/token"
        assert token_dir in mounts(found[name])
    for name, container in found.items():
        if name not in ("tif", "tof"):
            assert token_dir not in mounts(container), name


def test_azure_account_key_or_sas_is_a_secret_reference(monkeypatch):
    """An account key or a SAS token comes from the Secret; either may be absent."""
    monkeypatch.setenv("POIESIS_AZURE_ENABLED", "true")
    monkeypatch.setenv("POIESIS_AZURE_ACCOUNT_NAME", "poiesisdata")
    monkeypatch.setenv("POIESIS_TASKPOD_AZURE_SECRET", "poiesis-azure")
    monkeypatch.setenv("POIESIS_AZURE_ENDPOINT", "https://poiesisdata.privatelink")
    spec = pod("az://container/blob")
    found = containers(spec)
    for key in ("AZURE_STORAGE_ACCOUNT_KEY", "AZURE_STORAGE_SAS_TOKEN"):
        ref = env(found["tif"])[key]["valueFrom"]["secretKeyRef"]
        assert ref == {"name": "poiesis-azure", "key": key, "optional": True}
    assert env(found["tof"])["AZURE_STORAGE_ENDPOINT"]["value"] == (
        "https://poiesisdata.privatelink"
    )
    for name, container in found.items():
        if name not in ("tif", "tof"):
            assert "AZURE_STORAGE_SAS_TOKEN" not in env(container), name
            assert "AZURE_STORAGE_ENDPOINT" not in env(container), name
    assert not [v for v in spec["volumes"] if v["name"] == "azure-identity-token"]


# --- What is offered -----------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "url"),
    [
        ({}, "gs://bucket/key"),
        ({}, "az://container/blob"),
        ({"POIESIS_S3_ENABLED": "true"}, "gs://bucket/key"),
    ],
)
def test_a_provider_that_is_off_is_refused_at_submit(monkeypatch, values, url):
    """Its scheme is a 400 naming the provider."""
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="no .* credentials"):
        pod(url)


def test_s3_with_workload_identity_is_not_refused(monkeypatch):
    """The 400 for unconfigured S3 does not fire for a role without keys."""
    monkeypatch.setenv("POIESIS_S3_ROLE_ARN", ROLE)
    pod("s3://bucket/key")


def service_storage(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`storage` of the service-info built from the current environment."""
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    response = TestClient(create_app()).get("/ga4gh/tes/v1/service-info")
    return response.json()["storage"]


def test_service_info_lists_only_enabled_object_stores(monkeypatch):
    """No provider on: FTP(S) and HTTP(S) only."""
    assert service_storage(monkeypatch) == ["ftp://", "ftps://", "http://", "https://"]


def test_service_info_lists_each_enabled_provider(monkeypatch):
    """Each enabled provider's scheme is listed."""
    monkeypatch.setenv("POIESIS_S3_ENABLED", "true")
    monkeypatch.setenv("POIESIS_GCS_ENABLED", "true")
    monkeypatch.setenv("POIESIS_TASKPOD_GCS_SECRET", "poiesis-gcs")
    monkeypatch.setenv("POIESIS_AZURE_ENABLED", "true")
    monkeypatch.setenv("POIESIS_AZURE_ACCOUNT_NAME", "poiesisdata")
    assert service_storage(monkeypatch) == [
        "az://",
        "ftp://",
        "ftps://",
        "gs://",
        "http://",
        "https://",
        "s3://",
    ]


def test_service_info_lists_s3_for_a_key_secret(monkeypatch):
    """Existing installs with `s3.existingSecret` keep `s3://`."""
    monkeypatch.setenv("POIESIS_TASKPOD_S3_SECRET", "poiesis-s3")
    assert "s3://" in service_storage(monkeypatch)
