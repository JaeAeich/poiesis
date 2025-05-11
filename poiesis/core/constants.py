"""Constants used in core services."""

import os
from dataclasses import dataclass
from functools import lru_cache

from kubernetes.client.models import (
    V1ConfigMapKeySelector,
    V1EnvVar,
    V1EnvVarSource,
    V1SecretKeySelector,
)


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
            POIESIS_IMAGE: The Poiesis image.
            COMMON_PVC_VOLUME_NAME: The common PVC volume name.
            FILER_PVC_PATH: The path in the PVC for the filer.
            S3_SECRET_NAME: The S3 K8s secret name.
            REDIS_SECRET_NAME: The redis K8s secret name.
            MONGODB_SECRET_NAME: The mongo K8s secret name.
            SERVICE_ACCOUNT_NAME: The K8s service account name that allows core
                component to interact with K8s API and create, list and delete pods.
            BACKOFF_LIMIT: The backoff limit for Job.
            CONFIGMAP_NAME: The configmap name for the core services.
        """

        K8S_NAMESPACE = os.getenv("POIESIS_K8S_NAMESPACE", "poiesis")
        TORC_PREFIX = "torc"
        TIF_PREFIX = "tif"
        TE_PREFIX = "te"
        TOF_PREFIX = "tof"
        PVC_PREFIX = "pvc"
        TEXAM_PREFIX = "texam"
        PVC_DEFAULT_DISK_SIZE = "1Gi"
        POIESIS_IMAGE = os.getenv("POIESIS_IMAGE", "docker.io/jaeaeich/poiesis:latest")
        COMMON_PVC_VOLUME_NAME = "task-pvc-volume"
        FILER_PVC_PATH = "/transfer"
        REDIS_SECRET_NAME = os.getenv("POIESIS_REDIS_SECRET_NAME")
        S3_SECRET_NAME = os.getenv("POIESIS_S3_SECRET_NAME")
        MONGODB_SECRET_NAME = os.getenv("POIESIS_MONGO_SECRET_NAME")
        SERVICE_ACCOUNT_NAME = os.getenv("POIESIS_SERVICE_ACCOUNT_NAME")
        BACKOFF_LIMIT = os.getenv("BACKOFF_LIMIT", "1")
        CONFIGMAP_NAME = os.getenv("POIESIS_CORE_CONFIGMAP_NAME")

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
def get_message_broker_envs() -> list[V1EnvVar]:
    """Get the env vars for redis.

    Used in k8s manifest for `tif`, `torc` etc.
    """
    return [
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
    ]


@lru_cache
def get_mongo_envs() -> list[V1EnvVar]:
    """Get the env vars for mongo.

    Used in k8s manifest for `tif`, `torc` etc.
    """
    return [
        V1EnvVar(
            name="MONGODB_USER",
            value_from=V1EnvVarSource(
                secret_key_ref=V1SecretKeySelector(
                    name=core_constants.K8s.MONGODB_SECRET_NAME,
                    key="MONGODB_USER",
                )
            ),
        ),
        V1EnvVar(
            name="MONGODB_PASSWORD",
            value_from=V1EnvVarSource(
                secret_key_ref=V1SecretKeySelector(
                    name=core_constants.K8s.MONGODB_SECRET_NAME,
                    key="MONGODB_PASSWORD",
                )
            ),
        ),
        V1EnvVar(
            name="MONGODB_HOST",
            value_from=V1EnvVarSource(
                config_map_key_ref=V1ConfigMapKeySelector(
                    name=core_constants.K8s.CONFIGMAP_NAME,
                    key="MONGODB_HOST",
                )
            ),
        ),
        V1EnvVar(
            name="MONGODB_PORT",
            value_from=V1EnvVarSource(
                config_map_key_ref=V1ConfigMapKeySelector(
                    name=core_constants.K8s.CONFIGMAP_NAME,
                    key="MONGODB_PORT",
                )
            ),
        ),
    ]


@lru_cache
def get_s3_envs() -> list[V1EnvVar]:
    """Get the env vars for s3.

    Used in k8s manifest for `tif`, `tof`.
    """
    return [
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
    ]


@lru_cache
def get_secret_names() -> list[V1EnvVar]:
    """Returns name of the secrets as env."""
    return [
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
    ]


@lru_cache
def get_configmap_names() -> list[V1EnvVar]:
    """Get names of the configmap."""
    return [
        V1EnvVar(
            name="POIESIS_CORE_CONFIGMAP_NAME", value=core_constants.K8s.CONFIGMAP_NAME
        ),
    ]
