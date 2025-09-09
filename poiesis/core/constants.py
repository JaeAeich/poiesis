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
    V1PodSecurityContext,
    V1SecretKeySelector,
    V1SecurityContext,
    V1Volume,
    V1VolumeMount,
)
from pydantic import ValidationError

from poiesis.api.exceptions import InternalServerException
from poiesis.core.adaptors.kubernetes.models import (
    V1PodSecurityContextPydanticModel,
    V1SecurityContextPydanticModel,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoiesisCoreConstants:
    """Constants used in core services.

    Attributes:
        K8s: Constants used in Kubernetes.
        MessageBroker: Constants used in message broker.
        Texam: Constants used in Texam.
    """

    @dataclass(frozen=True)
    class K8s:
        """Constants used in Kubernetes.

        Attributes:
            K8S_NAMESPACE: The namespace in Kubernetes.
            TORC_PREFIX: The prefix for the Task Orchestrator job name.
            TIF_PREFIX: The prefix for the Task Input Filer job name.
            TE_PREFIX: The prefix for the Task Executor pod name.
            TOF_PREFIX: The prefix for the Task Output Filer job name.
            PVC_PREFIX: The prefix for the Persistent Volume Claim name.
            TEXAM_PREFIX: The prefix for the Texam job name.
            PVC_DEFAULT_DISK_SIZE: The default disk size for the Persistent Volume
                Claim.
                        PVC_ACCESS_MODE: The access mode for PVCs (e.g., ReadWriteOnce,
                ReadWriteMany). Defaults to ReadWriteOnce for compatibility with
                most storage providers.
            PVC_STORAGE_CLASS: The storage class name for PVCs. Defaults to
                'standard' which is commonly available across different K8s
                distributions.
            POIESIS_IMAGE: The Poiesis image.
            COMMON_PVC_VOLUME_NAME: The common PVC volume name.
            FILER_PVC_PATH: The path in the PVC for the filer.
            S3_SECRET_NAME: The S3 K8s secret name.
            REDIS_SECRET_NAME: The redis K8s secret name.
            MONGODB_SECRET_NAME: The mongo K8s secret name.
            POIESIS_MONGODB_URI_SECRET_KEY: The mongo K8s secret key.
            SERVICE_ACCOUNT_NAME: The K8s service account name that allows core
                component to interact with K8s API and create, list and delete pods.
            BACKOFF_LIMIT: The backoff limit for Job.
            CONFIGMAP_NAME: The configmap name for the core services.
            RESTART_POLICY: Restart policy for pods.
            IMAGE_PULL_POLICY: Image pull policy.
            JOB_TTL: Time in seconds after which the completed or failed job will be
                removed.
        """

        K8S_NAMESPACE = os.getenv("POIESIS_K8S_NAMESPACE", "poiesis")
        TORC_PREFIX = "torc"
        TIF_PREFIX = "tif"
        TE_PREFIX = "te"
        TOF_PREFIX = "tof"
        PVC_PREFIX = "pvc"
        TEXAM_PREFIX = "texam"
        PVC_DEFAULT_DISK_SIZE = "1Gi"
        PVC_ACCESS_MODE = os.getenv("POIESIS_PVC_ACCESS_MODE")
        PVC_STORAGE_CLASS = os.getenv("POIESIS_PVC_STORAGE_CLASS")
        POIESIS_IMAGE = os.getenv("POIESIS_IMAGE", "docker.io/jaeaeich/poiesis:latest")
        COMMON_PVC_VOLUME_NAME = "task-pvc-volume"
        FILER_PVC_PATH = "/transfer"
        REDIS_SECRET_NAME = os.getenv("POIESIS_REDIS_SECRET_NAME")
        S3_SECRET_NAME = os.getenv("POIESIS_S3_SECRET_NAME")
        MONGODB_SECRET_NAME = os.getenv("POIESIS_MONGODB_SECRET_NAME")
        POIESIS_MONGODB_URI_SECRET_KEY = os.getenv(
            "POIESIS_MONGODB_URI_SECRET_KEY", "MONGODB_URI"
        )
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

    @dataclass(frozen=True)
    class Texam:
        """Constants used in Texam.

        Attributes:
            BACKOFF_LIMIT: The maximum time is second to wait in exponential backoff.
                starting from 1 second for a failing executor pod.
            POLL_INTERVAL: The interval in seconds to poll the executor pod status as
                a fallback strategy if watch is not available.
            MONITOR_TIMEOUT_SECONDS: The timeout in seconds to monitor the executor pod
                status.
                Default to 0, which means infinity.
        """

        BACKOFF_LIMIT = 60
        POLL_INTERVAL = 10
        MONITOR_TIMEOUT_SECONDS = 0


@lru_cache
def get_poiesis_core_constants() -> PoiesisCoreConstants:
    """Get the Poiesis core constants.

    Returns:
        PoesisCoreConstants: The Poiesis core constants.
    """
    return PoiesisCoreConstants()


core_constants = get_poiesis_core_constants()


@lru_cache
def get_message_broker_envs() -> tuple[V1EnvVar, ...]:
    """Get the env vars for redis.

    Used in k8s manifest for `tif`, `torc` etc.
    """
    common = (
        V1EnvVar(
            name="MESSAGE_BROKER_HOST",
            value_from=V1EnvVarSource(
                config_map_key_ref=V1ConfigMapKeySelector(
                    name=core_constants.K8s.CONFIGMAP_NAME,
                    key="MESSAGE_BROKER_HOST",
                )
            ),
        ),
        V1EnvVar(
            name="MESSAGE_BROKER_PORT",
            value_from=V1EnvVarSource(
                config_map_key_ref=V1ConfigMapKeySelector(
                    name=core_constants.K8s.CONFIGMAP_NAME,
                    key="MESSAGE_BROKER_PORT",
                )
            ),
        ),
    )

    auth = (
        V1EnvVar(
            name="MESSAGE_BROKER_PASSWORD",
            value_from=V1EnvVarSource(
                secret_key_ref=V1SecretKeySelector(
                    name=core_constants.K8s.REDIS_SECRET_NAME,
                    key="MESSAGE_BROKER_PASSWORD",
                    optional=True,
                )
            ),
        ),
    )

    return common + auth if core_constants.K8s.REDIS_SECRET_NAME else common


@lru_cache
def get_mongo_envs() -> tuple[V1EnvVar, ...]:
    """Get the env vars for mongo.

    Used in k8s manifest for `tif`, `torc` etc.
    """
    auth = (
        V1EnvVar(
            name="POIESIS_MONGODB_URI_SECRET_KEY",
            value_from=V1EnvVarSource(
                config_map_key_ref=V1ConfigMapKeySelector(
                    name=core_constants.K8s.CONFIGMAP_NAME,
                    key="POIESIS_MONGODB_URI_SECRET_KEY",
                    optional=True,
                )
            ),
        ),
        V1EnvVar(
            name=core_constants.K8s.POIESIS_MONGODB_URI_SECRET_KEY,
            value_from=V1EnvVarSource(
                secret_key_ref=V1SecretKeySelector(
                    name=core_constants.K8s.MONGODB_SECRET_NAME,
                    key=core_constants.K8s.POIESIS_MONGODB_URI_SECRET_KEY,
                    optional=True,
                )
            ),
        ),
    )

    if not core_constants.K8s.MONGODB_SECRET_NAME:
        logger.error("MongoDB secret name is not set")
        raise ValueError("MongoDB secret name is not set")

    return auth


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
        )
        if core_constants.K8s.S3_SECRET_NAME
        else ()
    )


@lru_cache
def get_secret_names() -> tuple[V1EnvVar, ...]:
    """Returns name of the secrets as env."""
    return (
        V1EnvVar(
            name="POIESIS_S3_SECRET_NAME",
            value_from=V1EnvVarSource(
                config_map_key_ref=V1ConfigMapKeySelector(
                    name=core_constants.K8s.CONFIGMAP_NAME,
                    key="POIESIS_S3_SECRET_NAME",
                    optional=True,
                )
            ),
        ),
        V1EnvVar(
            name="POIESIS_MONGO_SECRET_NAME",
            value_from=V1EnvVarSource(
                config_map_key_ref=V1ConfigMapKeySelector(
                    name=core_constants.K8s.CONFIGMAP_NAME,
                    key="POIESIS_MONGO_SECRET_NAME",
                )
            ),
        ),
        V1EnvVar(
            name="POIESIS_REDIS_SECRET_NAME",
            value_from=V1EnvVarSource(
                config_map_key_ref=V1ConfigMapKeySelector(
                    name=core_constants.K8s.CONFIGMAP_NAME,
                    key="POIESIS_REDIS_SECRET_NAME",
                    optional=True,
                ),
            ),
        ),
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
        InternalServerException: If the file doesn't exist or can't be read
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
            raise InternalServerException("Security context path is not set.")
        file_path = Path(str(security_context_path)) / filename

        if not file_path.exists():
            raise InternalServerException(f"Security context file {filename} not found")

        with open(file_path) as f:
            context: dict[str, Any] = json.load(f)
            if not context:
                logger.warning(f"Security context is empty in {filename}.")
            logger.debug(f"Security context: \n{json.dumps(context, indent=2)}")
            return context
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        raise InternalServerException(
            "Failed to read security context JSON file"
        ) from e


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
        raise InternalServerException(f"Failed to validate {filename}") from e


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
        raise InternalServerException(f"Failed to validate {filename}") from e


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
        raise InternalServerException(f"Failed to validate {filename}") from e


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
        raise InternalServerException(f"Failed to validate {filename}") from e


@lru_cache
def get_infrastructure_security_volume() -> list[V1Volume]:
    """Returns the name of the security context configmap."""
    if not core_constants.K8s.INFRASTRUCTURE_SECURITY_CONTEXT_ENABLED:
        return []

    if (
        not core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME
        or not core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME.strip()
    ):
        raise InternalServerException(
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
        raise InternalServerException("Security context configmap name is not set.")

    if not core_constants.K8s.SECURITY_CONTEXT_PATH:
        raise InternalServerException("Security context path is not set.")

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
        raise InternalServerException("Security context configmap name is not set.")

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
        raise InternalServerException("Security context configmap name is not set.")

    if not core_constants.K8s.SECURITY_CONTEXT_PATH:
        raise InternalServerException("Security context path is not set.")

    return [
        V1VolumeMount(
            name=str(core_constants.K8s.SECURITY_CONTEXT_CONFIGMAP_NAME),
            mount_path=core_constants.K8s.SECURITY_CONTEXT_PATH,
            read_only=True,
        )
    ]


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
