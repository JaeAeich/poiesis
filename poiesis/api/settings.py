"""API-side settings derived from environment variables.

Single place that reads env. Held in a Pydantic settings object so the
TaskPod RuntimeConfig and the database DSN come from one validated source.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from poiesis.core.taskpod import RuntimeConfig

DEFAULT_POIESIS_IMAGE = "docker.io/jaeaeich/poiesis:latest"


class Settings(BaseModel):
    """API runtime settings."""

    postgres_dsn: str = Field(
        default_factory=lambda: os.environ.get(
            "POSTGRES_DSN",
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

    def runtime_config(self) -> RuntimeConfig:
        """Materialise the TaskPod RuntimeConfig used by the spec builder."""
        return RuntimeConfig(
            namespace=self.poiesis_namespace,
            poiesis_image=self.poiesis_image,
            pvc_storage_class=self.pvc_storage_class,
            pvc_access_mode=self.pvc_access_mode,
            taskpod_service_account=self.taskpod_service_account,
        )


def load_settings() -> Settings:
    """Construct Settings from the current process environment."""
    return Settings()
