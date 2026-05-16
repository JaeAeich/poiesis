"""API-side settings derived from environment variables.

Single place that reads env. Held in a Pydantic settings object so the
TaskPod RuntimeConfig and the database DSN come from one validated source.
"""

from __future__ import annotations

import os

from kubernetes.client import V1EnvVar
from pydantic import BaseModel, Field

from poiesis.core.taskpod import RuntimeConfig

DEFAULT_POIESIS_IMAGE = "docker.io/jaeaeich/poiesis:latest"


class Settings(BaseModel):
    """API runtime settings."""

    database_url: str = Field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/poiesis",
        ),
    )
    poiesis_namespace: str = Field(
        default_factory=lambda: os.environ.get("POIESIS_K8S_NAMESPACE", "poiesis"),
    )
    poiesis_image: str = Field(
        default_factory=lambda: os.environ.get("POIESIS_IMAGE", DEFAULT_POIESIS_IMAGE),
    )
    pvc_storage_class: str | None = Field(
        default_factory=lambda: os.environ.get("POIESIS_PVC_STORAGE_CLASS") or None,
    )
    pvc_access_mode: str = Field(
        default_factory=lambda: os.environ.get(
            "POIESIS_PVC_ACCESS_MODE", "ReadWriteOnce"
        ),
    )
    taskpod_service_account: str | None = Field(
        default_factory=lambda: (
            os.environ.get("POIESIS_TASKPOD_SERVICE_ACCOUNT") or None
        ),
    )
    s3_url: str | None = Field(
        default_factory=lambda: os.environ.get("S3_URL") or None,
    )
    aws_access_key_id: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_ACCESS_KEY_ID") or None,
    )
    aws_secret_access_key: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_SECRET_ACCESS_KEY") or None,
    )
    aws_region: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_REGION") or None,
    )

    def runtime_config(self) -> RuntimeConfig:
        """Materialise the TaskPod RuntimeConfig used by the spec builder."""
        env = [V1EnvVar(name="DATABASE_URL", value=self.database_url)]
        # Propagate s3 creds only when set; tasks with no s3 i/o don't need them.
        for name, value in (
            ("S3_URL", self.s3_url),
            ("AWS_ACCESS_KEY_ID", self.aws_access_key_id),
            ("AWS_SECRET_ACCESS_KEY", self.aws_secret_access_key),
            ("AWS_REGION", self.aws_region),
        ):
            if value is not None:
                env.append(V1EnvVar(name=name, value=value))
        return RuntimeConfig(
            namespace=self.poiesis_namespace,
            poiesis_image=self.poiesis_image,
            pvc_storage_class=self.pvc_storage_class,
            pvc_access_mode=self.pvc_access_mode,
            taskpod_service_account=self.taskpod_service_account,
            extra_env=env,
        )


def load_settings() -> Settings:
    """Construct Settings from the current process environment."""
    return Settings()
