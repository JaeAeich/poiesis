"""TaskPod Jobs must not carry the database URL or the S3 keys (#154).

`Settings.runtime_config()` used to put them on trec, tif and tof as literal
env values, so anyone who could read Jobs or Pods in the task namespace could
read them. With Secret names configured they are `secretKeyRef`s instead.
"""

from __future__ import annotations

import json
import logging

import pytest
from kubernetes.client import ApiClient, V1Container

from poiesis.api.settings import AuthSettings, Settings
from poiesis.api.tes.models import TesExecutor, TesInput, TesOutput, TesTask
from poiesis.core.taskpod import build_taskpod_job

DSN = "postgresql://poiesis:db-pass-hunter2@db.example.org:5432/poiesis"
SECRETS = {
    "DATABASE_URL": DSN,
    "AWS_ACCESS_KEY_ID": "AKIAHUNTER2KEYID",
    "AWS_SECRET_ACCESS_KEY": "s3-hunter2-access-key",
    "AWS_SESSION_TOKEN": "s3-hunter2-session-token",
}
CREDENTIAL_NAMES = {*SECRETS, "AWS_ENDPOINT_URL", "AWS_REGION"}

TASK = TesTask(
    id="t1",
    inputs=[TesInput(path="/data/in", url="s3://bucket/in")],
    outputs=[TesOutput(path="/data/out", url="s3://bucket/out")],
    executors=[TesExecutor(image="busybox:1.36", command=["true"])],
)


@pytest.fixture(autouse=True)
def _api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API's own environment: it holds every credential as a value."""
    for name in ("POIESIS_TASKPOD_DATABASE_SECRET", "POIESIS_TASKPOD_S3_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("POIESIS_TASKPOD_DATABASE_SECRET_KEY", raising=False)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://s3.example.org:9000")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")


def containers(task: TesTask = TASK) -> dict[str, V1Container]:
    """Every container of the Job built from the current environment."""
    config = Settings(auth=AuthSettings(enabled=False)).runtime_config()
    _, job = build_taskpod_job(task, config)
    spec = job.spec.template.spec
    return {c.name: c for c in [*(spec.init_containers or []), *spec.containers]}


def manifest() -> str:
    """The Job and PVC as sent to Kubernetes."""
    config = Settings(auth=AuthSettings(enabled=False)).runtime_config()
    return json.dumps(
        ApiClient().sanitize_for_serialization(list(build_taskpod_job(TASK, config)))
    )


def env_of(container: V1Container) -> dict[str, dict]:
    """A container's env as serialised dicts, by name."""
    entries = ApiClient().sanitize_for_serialization(container.env or [])
    return {entry["name"]: entry for entry in entries}


def owned(found: dict[str, V1Container]) -> list[V1Container]:
    """The poiesis-owned containers that talk to the database or S3."""
    picked = [
        c
        for c in found.values()
        if c.command[0] == "poiesis" and c.command[1] in {"trec", "tif", "tof"}
    ]
    assert {c.command[1] for c in picked} == {"trec", "tif", "tof"}
    return picked


def test_no_secret_value_in_manifest(monkeypatch, caplog):
    """With Secret names set, no credential value is in the Job."""
    monkeypatch.setenv("POIESIS_TASKPOD_DATABASE_SECRET", "task-db")
    monkeypatch.setenv("POIESIS_TASKPOD_DATABASE_SECRET_KEY", "dsn")
    monkeypatch.setenv("POIESIS_TASKPOD_S3_SECRET", "task-s3")
    with caplog.at_level(logging.WARNING, logger="poiesis.api.settings"):
        rendered = manifest()
    for value in (*SECRETS.values(), "db-pass-hunter2"):
        assert value not in rendered
    assert "Job spec" not in caplog.text

    for container in owned(containers()):
        env = env_of(container)
        assert env["DATABASE_URL"] == {
            "name": "DATABASE_URL",
            "valueFrom": {"secretKeyRef": {"name": "task-db", "key": "dsn"}},
        }
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
            assert env[name]["valueFrom"] == {
                "secretKeyRef": {"name": "task-s3", "key": name}
            }
        # Optional: long-lived keys have no session token.
        assert env["AWS_SESSION_TOKEN"]["valueFrom"] == {
            "secretKeyRef": {
                "name": "task-s3",
                "key": "AWS_SESSION_TOKEN",
                "optional": True,
            }
        }
        # Not secret, so still plain values.
        assert env["AWS_ENDPOINT_URL"]["value"] == "http://s3.example.org:9000"
        assert env["AWS_REGION"]["value"] == "eu-central-1"


def test_database_secret_key_defaults_to_database_url(monkeypatch):
    """The key in the database Secret is `DATABASE_URL` unless set."""
    monkeypatch.setenv("POIESIS_TASKPOD_DATABASE_SECRET", "task-db")
    for container in owned(containers()):
        ref = env_of(container)["DATABASE_URL"]["valueFrom"]["secretKeyRef"]
        assert ref == {"name": "task-db", "key": "DATABASE_URL"}


def test_no_s3_secret_and_no_keys_adds_no_s3_credentials(monkeypatch):
    """Workload identity: no S3 Secret and no keys means no AWS key env."""
    monkeypatch.setenv("POIESIS_TASKPOD_DATABASE_SECRET", "task-db")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name)
    # Without S3 credentials an s3:// URL is refused at submit (#166).
    http_task = TASK.model_copy(
        update={
            "inputs": [TesInput(path="/data/in", url="https://example.org/in")],
            "outputs": [TesOutput(path="/data/out", url="https://example.org/out")],
        }
    )
    for container in owned(containers(http_task)):
        assert not {
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
        } & set(env_of(container))


def test_fallback_copies_values_and_warns_once(caplog):
    """Without Secret names (local runs) the values are copied, with a warning."""
    with caplog.at_level(logging.WARNING, logger="poiesis.api.settings"):
        found = containers()
    for container in owned(found):
        env = env_of(container)
        for name, value in SECRETS.items():
            assert env[name] == {"name": name, "value": value}
    warnings = [r for r in caplog.records if "Job spec" in r.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert warnings[0].levelno == logging.WARNING
    for name in SECRETS:
        assert name in message
    for value in SECRETS.values():
        assert value not in message


def test_fallback_warns_only_about_what_is_copied(monkeypatch, caplog):
    """A database Secret alone still leaves the S3 keys copied, and says so."""
    monkeypatch.setenv("POIESIS_TASKPOD_DATABASE_SECRET", "task-db")
    with caplog.at_level(logging.WARNING, logger="poiesis.api.settings"):
        rendered = manifest()
    assert DSN not in rendered
    assert SECRETS["AWS_SECRET_ACCESS_KEY"] in rendered
    (warning,) = [r for r in caplog.records if "Job spec" in r.getMessage()]
    assert "AWS_SECRET_ACCESS_KEY" in warning.getMessage()
    assert "DATABASE_URL into" not in warning.getMessage()


@pytest.mark.parametrize("secrets", [True, False])
def test_executors_get_no_credentials(monkeypatch, secrets):
    """Executors get none of the variables, by reference or by value."""
    if secrets:
        monkeypatch.setenv("POIESIS_TASKPOD_DATABASE_SECRET", "task-db")
        monkeypatch.setenv("POIESIS_TASKPOD_S3_SECRET", "task-s3")
    executors = [c for c in containers().values() if c.image == "busybox:1.36"]
    assert executors
    for executor in executors:
        assert not CREDENTIAL_NAMES & set(env_of(executor))
        dumped = json.dumps(ApiClient().sanitize_for_serialization(executor))
        for value in (*SECRETS.values(), "task-db", "task-s3"):
            assert value not in dumped


def test_session_token_is_reserved(monkeypatch):
    """`taskpods.extraEnv` cannot redefine `AWS_SESSION_TOKEN`."""
    monkeypatch.setenv(
        "POIESIS_TASKPOD_EXTRA_ENV",
        json.dumps([{"name": "AWS_SESSION_TOKEN", "value": "x"}]),
    )
    with pytest.raises(ValueError, match="AWS_SESSION_TOKEN"):
        Settings(auth=AuthSettings(enabled=False))
