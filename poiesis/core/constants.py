"""Constants used in core services."""

import os


class PoiesisCoreConstants:
    """Constants used in core services."""

    class K8s:
        """Constants used in Kubernetes."""

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

    class MessageBroker:
        """Constants used in message broker."""

        MESSAGE_BROKER_HOST = os.getenv("MESSAGE_BROKER_HOST", "localhost")
        MESSAGE_BROKER_PORT = os.getenv("MESSAGE_BROKER_PORT", "6379")

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
