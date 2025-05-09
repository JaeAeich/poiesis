"""Constants used in core services."""

import os
from dataclasses import dataclass
from functools import lru_cache


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
            S3_SECRET_NAME: The S3 secret name.
            BACKOFF_LIMIT: The backoff limit for Job.
            CONFIGMAP_NAME: The configmap name for the core services.
        """

        K8S_NAMESPACE = "poiesis"
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
        S3_SECRET_NAME = "poiesis-s3-secret"  # nosec B105
        MONGODB_SECRET_NAME = "poiesis-mongo-secret"  # nosec B105
        BACKOFF_LIMIT = os.getenv("BACKOFF_LIMIT", "1")
        CONFIGMAP_NAME = "poiesis-core-configmap"

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
