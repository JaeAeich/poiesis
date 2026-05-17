"""API-side settings derived from environment variables.

Single place that reads env. Held in a Pydantic settings object so the
TaskPod RuntimeConfig and the database DSN come from one validated source.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

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


def _parse_json_array_env(name: str) -> list[dict[str, Any]]:
    """JSON-array-of-objects env value → list[dict].

    Empty/unset returns []. Invalid JSON or wrong shape raises so a
    misconfigured chart fails the api pod startup with a clear message.
    Used for operator-supplied taskpod extras (env / volumes /
    volume_mounts) where silently dropping a malformed entry would be
    worse than a loud failure.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise TypeError(f"{name} must encode a JSON array")
    items: list[dict[str, Any]] = []
    for idx, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise TypeError(f"{name}[{idx}] must be a JSON object")
        items.append({str(k): v for k, v in entry.items()})
    return items


#: Env-var names operators cannot redefine via ``taskpods.extraEnv``.
#: Collisions are rejected at Settings construction so the API pod fails
#: to start with a clear message rather than producing duplicate-env
#: rejection at every task submit.
_RESERVED_ENV_NAMES: frozenset[str] = frozenset(
    {
        "DATABASE_URL",
        "AWS_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "POIESIS_POD_NAME",
        "POIESIS_POD_NAMESPACE",
    }
)
_RESERVED_ENV_PREFIXES: tuple[str, ...] = ("POIESIS_",)

#: Volume names the chart already uses; operator extras cannot reuse these.
_RESERVED_VOLUME_NAMES: frozenset[str] = frozenset({"task-data", "postgres-ca", "tmp"})


def _check_reserved_env(entries: list[dict[str, Any]]) -> None:
    """Reject operator-supplied env that clashes with chart-internal names."""
    for idx, entry in enumerate(entries):
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"POIESIS_TASKPOD_EXTRA_ENV[{idx}] missing required 'name'"
            )
        if name in _RESERVED_ENV_NAMES or any(
            name.startswith(p) for p in _RESERVED_ENV_PREFIXES
        ):
            raise ValueError(
                f"POIESIS_TASKPOD_EXTRA_ENV[{idx}].name={name!r} collides with a "
                "chart-internal env var; pick a different name"
            )


def _check_reserved_volume(entries: list[dict[str, Any]], setting_name: str) -> None:
    """Reject operator-supplied volume/mount entries with reserved names."""
    for idx, entry in enumerate(entries):
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"{setting_name}[{idx}] missing required 'name'")
        if name in _RESERVED_VOLUME_NAMES:
            raise ValueError(
                f"{setting_name}[{idx}].name={name!r} is reserved by the chart"
            )


def _parse_and_check_env_extras() -> list[dict[str, Any]]:
    """Parse POIESIS_TASKPOD_EXTRA_ENV and reject reserved-name collisions."""
    entries = _parse_json_array_env("POIESIS_TASKPOD_EXTRA_ENV")
    _check_reserved_env(entries)
    return entries


def _parse_and_check_volume_extras(name: str) -> list[dict[str, Any]]:
    """Parse a volume/mount extras env and reject reserved-name collisions."""
    entries = _parse_json_array_env(name)
    _check_reserved_volume(entries, name)
    return entries


def _entries_to_envvars(entries: list[dict[str, Any]]) -> list[V1EnvVar]:
    """Convert JSON-shaped env entries to V1EnvVar instances.

    Supports the two common shapes:
    {"name": "X", "value": "1"}
    {"name": "X", "valueFrom": {"secretKeyRef": {...}}}
    """
    out: list[V1EnvVar] = []
    for entry in entries:
        name = entry["name"]
        if "value" in entry:
            out.append(V1EnvVar(name=name, value=str(entry["value"])))
        elif "valueFrom" in entry or "value_from" in entry:
            out.append(
                V1EnvVar(
                    name=name,
                    value_from=entry.get("valueFrom") or entry.get("value_from"),
                )
            )  # type: ignore[arg-type]
        else:
            out.append(V1EnvVar(name=name))
    return out


DEFAULT_POIESIS_IMAGE = "docker.io/jaeaeich/poiesis:latest"


class AuthSettings(BaseModel):
    """OIDC resource-server settings.

    Poiesis validates incoming JWTs directly against ``issuer``'s JWKS;
    it is not an OAuth client. When ``enabled`` is true, ``issuer`` and
    ``audience`` are required at startup — missing values fail loudly
    rather than silently disabling auth. When ``enabled`` is false the
    API serves all requests as a fixed anonymous principal.
    """

    enabled: bool = Field(
        default_factory=lambda: (
            os.environ.get("POIESIS_AUTH_ENABLED", "true").lower()
            not in {"0", "false", "no", "off"}
        ),
    )
    issuer: str = Field(
        default_factory=lambda: os.environ.get("POIESIS_AUTH_OIDC_ISSUER", ""),
    )
    audience: str = Field(
        default_factory=lambda: os.environ.get("POIESIS_AUTH_OIDC_AUDIENCE", ""),
    )
    jwks_cache_ttl: int = Field(
        default_factory=lambda: (
            _parse_int_env("POIESIS_AUTH_OIDC_JWKS_CACHE_TTL", 3600) or 3600
        ),
    )
    clock_skew: int = Field(
        default_factory=lambda: (
            _parse_int_env("POIESIS_AUTH_OIDC_CLOCK_SKEW", 30) or 30
        ),
    )
    principal_claim: str = Field(
        default_factory=lambda: os.environ.get(
            "POIESIS_AUTH_OIDC_PRINCIPAL_CLAIM", "sub"
        ),
    )
    required_scopes: tuple[str, ...] = Field(
        default_factory=lambda: _parse_csv_env("POIESIS_AUTH_OIDC_REQUIRED_SCOPES"),
    )

    def validate_required(self) -> None:
        """Raise if mandatory fields are missing. Called at app startup.

        No-op when auth is disabled — the validator is never built, so
        issuer/audience are irrelevant.
        """
        if not self.enabled:
            return
        missing = [
            name
            for name, value in (("issuer", self.issuer), ("audience", self.audience))
            if not value
        ]
        if missing:
            raise ValueError(
                "OIDC auth misconfigured: missing "
                + ", ".join(f"POIESIS_AUTH_OIDC_{m.upper()}" for m in missing)
            )


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
    # Operator-supplied TaskPod extensions, JSON-encoded via the chart.
    # All three are rejected on collision with chart-internal names at
    # construction so the api pod fails fast on misconfiguration.
    taskpod_extra_env: list[dict[str, Any]] = Field(
        default_factory=_parse_and_check_env_extras,
    )
    taskpod_extra_volumes: list[dict[str, Any]] = Field(
        default_factory=lambda: _parse_and_check_volume_extras(
            "POIESIS_TASKPOD_EXTRA_VOLUMES"
        ),
    )
    taskpod_extra_volume_mounts: list[dict[str, Any]] = Field(
        default_factory=lambda: _parse_and_check_volume_extras(
            "POIESIS_TASKPOD_EXTRA_VOLUME_MOUNTS"
        ),
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
    auth: AuthSettings = Field(default_factory=AuthSettings)

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
            taskpod_extra_env=_entries_to_envvars(self.taskpod_extra_env),
            taskpod_extra_volumes=self.taskpod_extra_volumes,
            taskpod_extra_volume_mounts=self.taskpod_extra_volume_mounts,
        )


def load_settings() -> Settings:
    """Construct Settings from the current process environment."""
    return Settings()
