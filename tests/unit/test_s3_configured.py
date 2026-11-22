"""Submit refuses `s3://` URLs when TaskPods get no S3 credentials (#166).

Such a task used to be accepted and fail in TIF or TOF with "AWS
credentials are not set".
"""

from __future__ import annotations

import pytest

from poiesis.api.settings import AuthSettings, Settings
from poiesis.tes.models import TesExecutor, TesInput, TesTask
from poiesis.core.taskpod import build_taskpod_job

TASK = TesTask(
    id="t1",
    inputs=[TesInput(path="/data/in", url="s3://bucket/in")],
    executors=[TesExecutor(image="busybox:1.36", command=["true"])],
)
S3_ENV = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_ENDPOINT_URL",
    "POIESIS_TASKPOD_S3_SECRET",
)


@pytest.fixture(autouse=True)
def _no_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    """An API environment without any S3 setting."""
    for name in S3_ENV:
        monkeypatch.delenv(name, raising=False)


def settings(**fields: object) -> Settings:
    return Settings(auth=AuthSettings(enabled=False), **fields)  # ty: ignore


def test_no_credentials_refuses_s3():
    """Neither a Secret nor keys: an s3:// input is a 400."""
    config = settings().runtime_config()
    assert not config.s3_configured
    with pytest.raises(ValueError, match="no S3 credentials"):
        build_taskpod_job(TASK, config)


@pytest.mark.parametrize(
    "fields",
    [
        {"taskpod_s3_secret": "poiesis-s3"},
        {"aws_access_key_id": "id", "aws_secret_access_key": "key"},
        {"taskpod_extra_env": [{"name": "AWS_ACCESS_KEY_ID", "value": "id"}]},
    ],
    ids=["secret", "api-values", "extra-env"],
)
def test_configured_credentials_accept_s3(fields):
    """Any source of an access key for the filers lets s3:// through."""
    config = settings(**fields).runtime_config()
    assert config.s3_configured
    build_taskpod_job(TASK, config)
