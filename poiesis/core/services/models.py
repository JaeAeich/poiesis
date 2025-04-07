"""Models for the core services."""

from enum import Enum


class PodPhase(Enum):
    """Pod phase enumeration."""

    PENDING = "Pending"
    RUNNING = "Running"
    UNKNOWN = "Unknown"
    FAILED = "Failed"
    SUCCEEDED = "Succeeded"
