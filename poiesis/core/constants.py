"""Constants used in core services."""

import os
from dataclasses import dataclass
from functools import lru_cache

from kubernetes.client.models import (
    V1Capabilities,
    V1ConfigMapKeySelector,
    V1EnvVar,
    V1EnvVarSource,
    V1PodSecurityContext,
    V1SeccompProfile,
    V1SecretKeySelector,
    V1SecurityContext,
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
        PVC_ACCESS_MODE = os.getenv("POIESIS_PVC_ACCESS_MODE", "ReadWriteOnce")
        PVC_STORAGE_CLASS = os.getenv("POIESIS_PVC_STORAGE_CLASS", "standard")
        POIESIS_IMAGE = os.getenv("POIESIS_IMAGE", "docker.io/jaeaeich/poiesis:latest")
        COMMON_PVC_VOLUME_NAME = "task-pvc-volume"
        FILER_PVC_PATH = "/transfer"
        REDIS_SECRET_NAME = os.getenv("POIESIS_REDIS_SECRET_NAME")
        S3_SECRET_NAME = os.getenv("POIESIS_S3_SECRET_NAME")
        MONGODB_SECRET_NAME = os.getenv("POIESIS_MONGO_SECRET_NAME")
        SERVICE_ACCOUNT_NAME = os.getenv("POIESIS_SERVICE_ACCOUNT_NAME")
        BACKOFF_LIMIT = os.getenv("BACKOFF_LIMIT", "1")
        CONFIGMAP_NAME = os.getenv("POIESIS_CORE_CONFIGMAP_NAME")
        RESTART_POLICY = os.getenv("POIESIS_RESTART_POLICY", "Never")
        IMAGE_PULL_POLICY = os.getenv("POIESIS_IMAGE_PULL_POLICY", "IfNotPresent")
        JOB_TTL = os.getenv("POIESIS_JOB_TTL")

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
    common = (
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
    )
    auth = (
        V1EnvVar(
            name="MONGODB_USER",
            value_from=V1EnvVarSource(
                secret_key_ref=V1SecretKeySelector(
                    name=core_constants.K8s.MONGODB_SECRET_NAME,
                    key="MONGODB_USER",
                    optional=True,
                )
            ),
        ),
        V1EnvVar(
            name="MONGODB_PASSWORD",
            value_from=V1EnvVarSource(
                secret_key_ref=V1SecretKeySelector(
                    name=core_constants.K8s.MONGODB_SECRET_NAME,
                    key="MONGODB_PASSWORD",
                    optional=True,
                )
            ),
        ),
    )

    return common + auth if core_constants.K8s.MONGODB_SECRET_NAME else common


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
                    optional=True,
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
def get_default_pod_security_context() -> V1PodSecurityContext:
    """Returns a default, hardened V1PodSecurityContext.

    This context enforces that all containers in the pod run as a non-root user
    and uses the 'OnRootMismatch' policy to speed up volume mounting.
    """
    return V1PodSecurityContext(
        run_as_non_root=True,
        seccomp_profile=V1SeccompProfile(type="RuntimeDefault"),
        fs_group=1001,
        fs_group_change_policy="OnRootMismatch",
    )


@lru_cache
def get_default_container_security_context() -> V1SecurityContext:
    """Returns a default, hardened V1SecurityContext for a container.

    This context enforces the principle of least privilege.
    """
    return V1SecurityContext(
        run_as_non_root=True,
        run_as_user=1001,
        run_as_group=1001,
        allow_privilege_escalation=False,
        capabilities=V1Capabilities(drop=["ALL"]),
    )


@lru_cache
def get_permissive_container_security_context() -> V1SecurityContext:
    """Returns a permissive V1SecurityContext for executor containers.

    This context is more permissive to support applications that require
    specific user/group permissions or capabilities.
    """
    return V1SecurityContext(
        run_as_non_root=False,
        allow_privilege_escalation=True,
        seccomp_profile=V1SeccompProfile(type="RuntimeDefault"),
        capabilities=V1Capabilities(
            drop=[
                "SYS_ADMIN",  # Block mount, pivot_root, remount, etc.
                "SYS_MODULE",  # Block kernel module loading
                "SYS_PTRACE",  # Block ptrace of other processes
                "SYS_TIME",  # Block system time modification
                "NET_ADMIN",  # Block network config (e.g., iptables, interfaces)
                "NET_RAW",  # Block raw sockets (ping, nmap, etc.)
                "NET_BIND_SERVICE",  # Block binding to ports <1024
                "NET_BROADCAST",  # Block sending network broadcasts
            ],
        ),
        privileged=False,  # Do not run as fully privileged container
    )


@lru_cache
def get_permissive_pod_security_context() -> V1PodSecurityContext:
    """Returns a permissive V1PodSecurityContext for executor pods.

    This context is more permissive to support applications that require
    specific user/group permissions for file access.
    """
    return V1PodSecurityContext(
        run_as_non_root=False,  # Allow running as root if needed
        seccomp_profile=V1SeccompProfile(type="RuntimeDefault"),
        fs_group_change_policy="Always",  # Allow changing file permissions
    )
