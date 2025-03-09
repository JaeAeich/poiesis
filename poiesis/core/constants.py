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
            S3_VOLUME_NAME: The S3 volume name.
            S3_MOUNT_PATH: The S3 mount path.
            S3_SECRET_NAME: The S3 secret name.
        """

        K8S_NAMESPACE = "poiesis"
        TORC_PREFIX = "torc"
        TIF_PREFIX = "tif"
        TE_PREFIX = "te"
        TOF_PREFIX = "tof"
        PVC_PREFIX = "pvc"
        TEXAM_PREFIX = "texam"
        PVC_DEFAULT_DISK_SIZE = "1Gi"
        POIESIS_IMAGE = "docker.io/jaeaeich/poiesis:latest"
        COMMON_PVC_VOLUME_NAME = "task-pvc-volume"
        FILER_PVC_PATH = "/transfer"
        S3_VOLUME_NAME = "s3-volume"
        S3_MOUNT_PATH = "/aws"
        S3_SECRET_NAME = "s3-secret"

    @dataclass(frozen=True)
    class MessageBroker:
        """Constants used in message broker.

        Attributes:
            MESSAGE_BROKER_HOST: The host of the message broker.
            MESSAGE_BROKER_PORT: The port of the message
        """

        MESSAGE_BROKER_HOST = os.getenv("MESSAGE_BROKER_HOST", "localhost")
        MESSAGE_BROKER_PORT = os.getenv("MESSAGE_BROKER_PORT", "6379")

    @dataclass(frozen=True)
    class Texam:
        """Constants used in Texam.

        Attributes:
            BACKOFF_LIMIT: The maximum time is second to wait in exponential backoff.
                starting from 1 second for a failing executor pod.
            POLL_INTERVAL: The interval in seconds to poll the executor pod status as
                a fallback strategy if watch is not available.
        """

        BACKOFF_LIMIT = 60
        POLL_INTERVAL = 10


@lru_cache
def get_poiesis_core_constants() -> PoiesisCoreConstants:
    """Get the Poiesis core constants.

    Returns:
        PoesisCoreConstants: The Poiesis core constants.
    """
    return PoiesisCoreConstants()
