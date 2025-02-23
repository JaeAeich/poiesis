"""Constants used in core services."""


class PoesisCoreConstants:
    """Constants used in core services."""

    class K8s:
        """Constants used in Kubernetes."""

        K8S_NAMESPACE = "poesis"
        TORC_PREFIX = "torc"
        TIF_PREFIX = "tif"
        TE_PREFIX = "tif-executor"
        TOF_PREFIX = "tof"
        PVC_PREFIX = "pvc"
        PVC_DEFAULT_DISK_SIZE = "1Gi"
