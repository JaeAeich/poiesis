"""Constants used in core services."""

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from kubernetes.client.models import (
    V1ConfigMapKeySelector,
    V1ConfigMapVolumeSource,
    V1EnvVar,
    V1EnvVarSource,
    V1KeyToPath,
    V1PodSecurityContext,
    V1SecretKeySelector,
    V1SecurityContext,
    V1Volume,
    V1VolumeMount,
)
from pydantic import ValidationError

from poiesis.api.exceptions import InternalServerError
from poiesis.core.adaptors.kubernetes.models import (
    V1PodSecurityContextPydanticModel,
    V1SecurityContextPydanticModel,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoiesisCoreConstants:
    """Constants used in core services."""

    @dataclass(frozen=True)
    class K8s:
        """Constants used in Kubernetes."""

        K8S_NAMESPACE = os.getenv("POIESIS_K8S_NAMESPACE", "poiesis")
        TIF_PREFIX = "tif"
        TOF_PREFIX = "tof"
        PVC_PREFIX = "pvc"
        TES_TASK_PREFIX = "tes-task"
        TES_TASK_CONFIGMAP_KEY = "task.json"
        TES_TASK_REQUEST_MOUNT_PATH = "/mnt/poiesis/tes"
        PVC_DEFAULT_DISK_SIZE = "1Gi"
        PVC_ACCESS_MODE = os.getenv("POIESIS_PVC_ACCESS_MODE")
        PVC_STORAGE_CLASS = os.getenv("POIESIS_PVC_STORAGE_CLASS")
        POIESIS_IMAGE = os.getenv("POIESIS_IMAGE", "docker.io/jaeaeich/poiesis:latest")
        COMMON_PVC_VOLUME_NAME = "task-pvc-volume"
        FILER_PVC_PATH = "/transfer"
        S3_SECRET_NAME = os.getenv("POIESIS_S3_SECRET_NAME")
        SERVICE_ACCOUNT_NAME = os.getenv("POIESIS_SERVICE_ACCOUNT_NAME")
        BACKOFF_LIMIT = 0
        CONFIGMAP_NAME = os.getenv("POIESIS_CORE_CONFIGMAP_NAME")
        RESTART_POLICY = os.getenv("POIESIS_RESTART_POLICY", "Never")
        IMAGE_PULL_POLICY = os.getenv("POIESIS_IMAGE_PULL_POLICY", "IfNotPresent")
        JOB_TTL = os.getenv("POIESIS_JOB_TTL")
        SECURITY_CONTEXT_CONFIGMAP_NAME = os.getenv(
            "POIESIS_SECURITY_CONTEXT_CONFIGMAP_NAME"
        )
        SECURITY_CONTEXT_PATH = os.getenv("POIESIS_SECURITY_CONTEXT_PATH")
        INFRASTRUCTURE_SECURITY_CONTEXT_ENABLED = (
            os.getenv("POIESIS_INFRASTRUCTURE_SECURITY_CONTEXT_ENABLED", "true").lower()
            == "true"
        )
        EXECUTOR_SECURITY_CONTEXT_ENABLED = (
            os.getenv("POIESIS_EXECUTOR_SECURITY_CONTEXT_ENABLED", "true").lower()
            == "true"
        )


@lru_cache
def get_poiesis_core_constants() -> PoiesisCoreConstants:
    """Get the Poiesis core constants.

    Returns:
        PoesisCoreConstants: The Poiesis core constants.
    """
    return PoiesisCoreConstants()


core_constants = get_poiesis_core_constants()


@lru_cache
def get_s3_envs() -> tuple[V1EnvVar, ...]:
    """Get the env vars for s3.

    Used in k8s manifest for `tif`, `tof`.
    """
    return (
        (
            V1EnvVar(
                name="S3_URL",
                value_from=V1EnvVarSource(
                    config_map_key_ref=V1ConfigMapKeySelector(
                        name=core_constants.K8s.CONFIGMAP_NAME,
                        key="S3_URL",
                        optional=True,
                    )
                ),
            ),
            V1EnvVar(
                name="AWS_ACCESS_KEY_ID",
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=core_constants.K8s.S3_SECRET_NAME,
                        key="AWS_ACCESS_KEY_ID",
                        optional=True,
                    )
                ),
            ),
            V1EnvVar(
                name="AWS_SECRET_ACCESS_KEY",
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=core_constants.K8s.S3_SECRET_NAME,
                        key="AWS_SECRET_ACCESS_KEY",
                        optional=True,
                    )
                ),
            ),
            V1EnvVar(
                name="AWS_REGION",
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=core_constants.K8s.S3_SECRET_NAME,
                        key="AWS_REGION",
                        optional=True,
                    )
                ),
            ),
            V1EnvVar(
                name="AWS_REQUEST_CHECKSUM_CALCULATION",
                value_from=V1EnvVarSource(
                    config_map_key_ref=V1ConfigMapKeySelector(
                        name=core_constants.K8s.CONFIGMAP_NAME,
                        key="AWS_REQUEST_CHECKSUM_CALCULATION",
                        optional=True,
                    )
                ),
            ),
            V1EnvVar(
                name="AWS_REQUEST_CHECKSUM_VALIDATION",
                value_from=V1EnvVarSource(
                    config_map_key_ref=V1ConfigMapKeySelector(
                        name=core_constants.K8s.CONFIGMAP_NAME,
                        key="AWS_REQUEST_CHECKSUM_VALIDATION",
                        optional=True,
                    )
                ),
            ),
        )
        if core_constants.K8s.S3_SECRET_NAME
        else ()
    )


@lru_cache
def get_configmap_names() -> tuple[V1EnvVar, ...]:
    """Get names of the configmap."""
    return (
        V1EnvVar(
            name="POIESIS_CORE_CONFIGMAP_NAME", value=core_constants.K8s.CONFIGMAP_NAME
        ),
    )


@lru_cache
def get_security_context_envs() -> tuple[V1EnvVar, ...]:
    """Get the env vars for security context."""
    return (
        V1EnvVar(
            name="POIESIS_SECURITY_CONTEXT_CONFIGMAP_NAME",
            value=core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME,
        ),
        V1EnvVar(
            name="POIESIS_SECURITY_CONTEXT_PATH",
            value=core_constants.K8s.SECURITY_CONTEXT_PATH,
        ),
        V1EnvVar(
            name="POIESIS_INFRASTRUCTURE_SECURITY_CONTEXT_ENABLED",
            value=str(core_constants.K8s.INFRASTRUCTURE_SECURITY_CONTEXT_ENABLED),
        ),
        V1EnvVar(
            name="POIESIS_EXECUTOR_SECURITY_CONTEXT_ENABLED",
            value=str(core_constants.K8s.EXECUTOR_SECURITY_CONTEXT_ENABLED),
        ),
    )


def _read_security_context_json(filename: str) -> dict[str, Any]:
    """Read a security context JSON file and return the parsed data.

    Args:
        filename: Name of the JSON file to read
            (e.g., "infrastructure_pod_security_context.json")

    Returns:
        Parsed JSON data as dict

    Raises:
        InternalServerError: If the file doesn't exist or can't be read
    """
    try:
        security_context_path = (
            core_constants.K8s.SECURITY_CONTEXT_PATH.strip()
            if core_constants.K8s.SECURITY_CONTEXT_PATH is not None
            else ""
        )
        if not security_context_path and (
            core_constants.K8s.INFRASTRUCTURE_SECURITY_CONTEXT_ENABLED
            or core_constants.K8s.EXECUTOR_SECURITY_CONTEXT_ENABLED
        ):
            raise InternalServerError("Security context path is not set.")
        file_path = Path(str(security_context_path)) / filename

        if not file_path.exists():
            raise InternalServerError(f"Security context file {filename} not found")

        with open(file_path) as f:
            context: dict[str, Any] = json.load(f)
            if not context:
                logger.warning(f"Security context is empty in {filename}.")
            logger.debug(f"Security context: \n{json.dumps(context, indent=2)}")
            return context
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        raise InternalServerError("Failed to read security context JSON file") from e


@lru_cache
def get_infrastructure_pod_security_context() -> V1PodSecurityContext | None:
    """Returns a V1PodSecurityContext for infrastructure components.

    Returns:
        V1PodSecurityContext: The security context for infrastructure components.
        None: If security context is disabled.
    """
    if not core_constants.K8s.INFRASTRUCTURE_SECURITY_CONTEXT_ENABLED:
        return None

    filename = "infrastructure_pod_security_context.json"
    json_data = _read_security_context_json(filename)
    try:
        return V1PodSecurityContextPydanticModel.model_validate(
            json_data
        ).to_k8s_model()
    except ValidationError as e:
        raise InternalServerError(f"Failed to validate {filename}") from e


@lru_cache
def get_infrastructure_container_security_context() -> V1SecurityContext | None:
    """Returns a V1SecurityContext for infrastructure containers.

    Returns:
        V1SecurityContext: The security context for infrastructure containers.
        None: If security context is disabled.
    """
    if not core_constants.K8s.INFRASTRUCTURE_SECURITY_CONTEXT_ENABLED:
        return None

    filename = "infrastructure_container_security_context.json"
    json_data = _read_security_context_json(filename)
    try:
        return V1SecurityContextPydanticModel.model_validate(json_data).to_k8s_model()
    except ValidationError as e:
        raise InternalServerError(f"Failed to validate {filename}") from e


@lru_cache
def get_executor_container_security_context() -> V1SecurityContext | None:
    """Returns a V1SecurityContext for task executor containers.

    Returns:
        V1SecurityContext: The security context for task executor containers.
        None: If security context is disabled.
    """
    if not core_constants.K8s.EXECUTOR_SECURITY_CONTEXT_ENABLED:
        return None

    filename = "executor_container_security_context.json"
    json_data = _read_security_context_json(filename)
    try:
        return V1SecurityContextPydanticModel.model_validate(json_data).to_k8s_model()
    except ValidationError as e:
        raise InternalServerError(f"Failed to validate {filename}") from e


@lru_cache
def get_executor_pod_security_context() -> V1PodSecurityContext | None:
    """Returns a V1PodSecurityContext for task executor pods.

    Returns:
        V1PodSecurityContext: The security context for task executor pods.
        None: If security context is disabled.
    """
    if not core_constants.K8s.EXECUTOR_SECURITY_CONTEXT_ENABLED:
        return None

    filename = "executor_pod_security_context.json"
    json_data = _read_security_context_json(filename)
    try:
        return V1PodSecurityContextPydanticModel.model_validate(
            json_data
        ).to_k8s_model()
    except ValidationError as e:
        raise InternalServerError(f"Failed to validate {filename}") from e


@lru_cache
def get_infrastructure_security_volume() -> list[V1Volume]:
    """Returns the name of the security context configmap."""
    if not core_constants.K8s.INFRASTRUCTURE_SECURITY_CONTEXT_ENABLED:
        return []

    if (
        not core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME
        or not core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME.strip()
    ):
        raise InternalServerError(
            "Security context configmap name is not set or is empty/whitespace."
        )

    return [
        V1Volume(
            name=str(core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME),
            config_map=V1ConfigMapVolumeSource(
                name=str(core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME)
            ),
        )
    ]


@lru_cache
def get_infrastructure_security_volume_mount() -> list[V1VolumeMount]:
    """Returns the name of the security context configmap."""
    if not core_constants.K8s.INFRASTRUCTURE_SECURITY_CONTEXT_ENABLED:
        return []

    if not core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME:
        raise InternalServerError("Security context configmap name is not set.")

    if not core_constants.K8s.SECURITY_CONTEXT_PATH:
        raise InternalServerError("Security context path is not set.")

    return [
        V1VolumeMount(
            name=str(core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME),
            mount_path=core_constants.K8s.SECURITY_CONTEXT_PATH,
            read_only=True,
        )
    ]


@lru_cache
def get_executor_security_volume() -> list[V1Volume]:
    """Returns the name of the security context configmap."""
    if not core_constants.K8s.EXECUTOR_SECURITY_CONTEXT_ENABLED:
        return []

    if not core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME:
        raise InternalServerError("Security context configmap name is not set.")

    return [
        V1Volume(
            name=str(core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME),
            config_map=V1ConfigMapVolumeSource(
                name=str(core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME)
            ),
        )
    ]


@lru_cache
def get_executor_security_volume_mount() -> list[V1VolumeMount]:
    """Returns the name of the security context configmap."""
    if not core_constants.K8s.EXECUTOR_SECURITY_CONTEXT_ENABLED:
        return []

    if not core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME:
        raise InternalServerError("Security context configmap name is not set.")

    if not core_constants.K8s.SECURITY_CONTEXT_PATH:
        raise InternalServerError("Security context path is not set.")

    return [
        V1VolumeMount(
            name=str(core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME),
            mount_path=core_constants.K8s.SECURITY_CONTEXT_PATH,
            read_only=True,
        )
    ]


def get_tes_task_request_volume_mounts() -> list[V1VolumeMount]:
    """Returns the volume mounts for the TES task request."""
    return [
        V1VolumeMount(
            name="tes-task-request",
            mount_path=core_constants.K8s.TES_TASK_REQUEST_MOUNT_PATH,
            read_only=True,
        )
    ]


def get_tes_task_request_volume(tes_task_id: str) -> list[V1Volume]:
    """Returns the volume for the TES task request."""
    return [
        V1Volume(
            name="tes-task-request",
            config_map=V1ConfigMapVolumeSource(
                name=f"{core_constants.K8s.TES_TASK_PREFIX}-{tes_task_id}",
                items=[
                    V1KeyToPath(
                        key=core_constants.K8s.TES_TASK_CONFIGMAP_KEY,
                        path=core_constants.K8s.TES_TASK_CONFIGMAP_KEY,
                    )
                ],
            ),
        ),
    ]


@lru_cache
def get_tes_task_request_path() -> Path:
    """Returns the full path to the TES task request file.

    Returns:
        Path: The complete file path combining the mount path and config key.
    """
    return (
        Path(core_constants.K8s.TES_TASK_REQUEST_MOUNT_PATH)
        / core_constants.K8s.TES_TASK_CONFIGMAP_KEY
    )


def get_labels(
    component: str,
    task_id: str,
    name: str | None = None,
    parent: str | None = None,
) -> dict[str, str]:
    """Get the labels for a job or a PVC.

    Args:
        component: The component that is creating the resource.
        task_id: The id of the task.
        name: The name of the resource.
        parent: The parent of the resource.

    Returns:
        The labels for the resource.
    """
    labels = {
        "app.kubernetes.io/component": component,
        "tes-task-id": task_id,
    }
    if name:
        labels["app.kubernetes.io/resource-name"] = name
    if parent:
        labels["app.kubernetes.io/part-of"] = parent

    return labels
