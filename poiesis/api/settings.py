"""API-side settings derived from environment variables.

Single place that reads env. Held in a Pydantic settings object so the
TaskPod RuntimeConfig and the database DSN come from one validated source.
"""

from __future__ import annotations

import json
import logging
import os

from kubernetes.client import V1EnvVar
from pydantic import BaseModel, Field

from poiesis.core.taskpod import PodSecurityEnforce, RuntimeConfig

logger = logging.getLogger(__name__)


def _parse_int_env(name: str, default: int | None = None) -> int | None:
    """Parse an int from env; empty/unset returns default; bad value raises."""
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _parse_optional_int_env(name: str) -> int | None:
    """Like _parse_int_env but returns None on empty AND on literal 'null'.

    Used for ``retain_after_seconds`` and ``max_disk_size_gi`` where the
    chart's ``null`` sentinel must reach the runtime as ``None``.
    """
    raw = os.environ.get(name, "")
    if raw == "" or raw.lower() in {"null", "none"}:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer or unset, got {raw!r}") from exc


def _parse_csv_env(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Comma-separated env value → tuple. Empty/unset returns default."""
    raw = os.environ.get(name, "")
    parts = tuple(s.strip() for s in raw.split(",") if s.strip())
    return parts or default


def _parse_json_object_env(name: str) -> dict[str, str]:
    """JSON-object env value → dict[str, str]. Empty/unset returns {}.

    Invalid JSON or non-object payloads log a warning and return {} so a
    malformed chart input degrades visibly rather than crashing startup.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("%s is not valid JSON; ignoring", name)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("%s must encode a JSON object; ignoring", name)
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


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
        default_factory=lambda: os.environ.get("POIESIS_NAMESPACE", "poiesis"),
    )
    # Defaults to poiesis_namespace via runtime_config() — operators can split
    # the control plane from the workload ns by setting POIESIS_TASKPOD_NAMESPACE.
    taskpod_namespace: str | None = Field(
        default_factory=lambda: os.environ.get("POIESIS_TASKPOD_NAMESPACE") or None,
    )
    poiesis_image: str = Field(
        default_factory=lambda: os.environ.get("POIESIS_IMAGE", DEFAULT_POIESIS_IMAGE),
    )
    # PVC storage class. Three states:
    #   None  → omit storageClassName, defer to cluster default
    #   ""    → explicit "no provisioning" (matches kubectl '-' sentinel
    #           which the chart converts to ""); requires a pre-bound PV
    #   other → use that StorageClass
    pvc_storage_class: str | None = Field(
        default_factory=lambda: (
            None
            if os.environ.get("POIESIS_PVC_STORAGE_CLASS") is None
            else os.environ.get("POIESIS_PVC_STORAGE_CLASS", "")
        ),
    )
    pvc_access_modes: tuple[str, ...] = Field(
        default_factory=lambda: _parse_csv_env(
            "POIESIS_PVC_ACCESS_MODES", default=("ReadWriteOnce",)
        ),
    )
    pvc_default_size_gi: int = Field(
        default_factory=lambda: _parse_int_env("POIESIS_PVC_DEFAULT_SIZE_GI", 1) or 1,
    )
    # None disables the cap entirely. Production charts MUST set this; the
    # schema enforces presence at chart-install time.
    pvc_max_size_gi: int | None = Field(
        default_factory=lambda: _parse_optional_int_env("POIESIS_PVC_MAX_SIZE_GI"),
    )
    pvc_labels: dict[str, str] = Field(
        default_factory=lambda: _parse_json_object_env("POIESIS_PVC_LABELS"),
    )
    pvc_annotations: dict[str, str] = Field(
        default_factory=lambda: _parse_json_object_env("POIESIS_PVC_ANNOTATIONS"),
    )
    # None → ttlSecondsAfterFinished is omitted on the Job entirely (audit
    # retention). Default 3600s matches the prior hardcoded behaviour.
    job_ttl_seconds: int | None = Field(
        default_factory=lambda: (
            _parse_optional_int_env("POIESIS_JOB_TTL_SECONDS")
            if "POIESIS_JOB_TTL_SECONDS" in os.environ
            else 3600
        ),
    )
    taskpod_service_account: str | None = Field(
        default_factory=lambda: (
            os.environ.get("POIESIS_TASKPOD_SERVICE_ACCOUNT") or None
        ),
    )
    pod_security_enforce: PodSecurityEnforce = Field(
        default_factory=lambda: PodSecurityEnforce(
            os.environ.get("POIESIS_POD_SECURITY_ENFORCE", "restricted")
        ),
    )
    # Comma-separated list of Secrets to attach as imagePullSecrets on every TaskPod.
    image_pull_secrets: tuple[str, ...] = Field(
        default_factory=lambda: tuple(
            s.strip()
            for s in os.environ.get("POIESIS_IMAGE_PULL_SECRETS", "").split(",")
            if s.strip()
        ),
    )
    postgres_ca_configmap: str | None = Field(
        default_factory=lambda: os.environ.get("POIESIS_POSTGRES_CA_CONFIGMAP") or None,
    )
    aws_endpoint_url: str | None = Field(
        default_factory=lambda: os.environ.get("AWS_ENDPOINT_URL") or None,
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
            ("AWS_ENDPOINT_URL", self.aws_endpoint_url),
            ("AWS_ACCESS_KEY_ID", self.aws_access_key_id),
            ("AWS_SECRET_ACCESS_KEY", self.aws_secret_access_key),
            ("AWS_REGION", self.aws_region),
        ):
            if value is not None:
                env.append(V1EnvVar(name=name, value=value))
        return RuntimeConfig(
            taskpod_namespace=self.taskpod_namespace or self.poiesis_namespace,
            poiesis_image=self.poiesis_image,
            pvc_storage_class=self.pvc_storage_class,
            pvc_access_modes=self.pvc_access_modes,
            pvc_default_size_gi=self.pvc_default_size_gi,
            pvc_max_size_gi=self.pvc_max_size_gi,
            pvc_labels=self.pvc_labels,
            pvc_annotations=self.pvc_annotations,
            taskpod_service_account=self.taskpod_service_account,
            job_ttl_seconds=self.job_ttl_seconds,
            pod_security_enforce=self.pod_security_enforce,
            image_pull_secrets=self.image_pull_secrets,
            postgres_ca_configmap=self.postgres_ca_configmap,
            extra_env=env,
        )


def load_settings() -> Settings:
    """Construct Settings from the current process environment."""
    return Settings()
