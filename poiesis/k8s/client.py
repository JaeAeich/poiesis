"""Async-friendly wrapper over the synchronous kubernetes Python client."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from kubernetes import client, config

if TYPE_CHECKING:
    from kubernetes.client import V1Job, V1PersistentVolumeClaim

logger = logging.getLogger(__name__)


def load_config() -> None:
    """Load the Kubernetes client configuration.

    Tries in-cluster first (works when Poiesis runs inside a Pod with a
    ServiceAccount), falls back to the local kubeconfig.
    """
    try:
        config.load_incluster_config()  # ty: ignore[unresolved-attribute]
        logger.info("Loaded in-cluster Kubernetes config")
    except config.ConfigException:  # ty: ignore[unresolved-attribute]
        config.load_kube_config()  # ty: ignore[unresolved-attribute]
        logger.info("Loaded local kubeconfig")


class K8sClient:
    """Async wrapper over `BatchV1Api` and `CoreV1Api`.

    Each method runs the underlying sync call in a worker thread via
    `asyncio.to_thread`. The wrapper holds no per-call state — instances
    are cheap and safe to share across requests.
    """

    def __init__(self) -> None:
        """Build the BatchV1/CoreV1 API clients. Requires `load_config()` first."""
        self._batch = client.BatchV1Api()
        self._core = client.CoreV1Api()

    async def create_pvc(
        self, namespace: str, pvc: V1PersistentVolumeClaim
    ) -> V1PersistentVolumeClaim:
        """Create a PVC, returning the server-side object (with uid populated)."""
        return await asyncio.to_thread(
            self._core.create_namespaced_persistent_volume_claim,
            namespace=namespace,
            body=pvc,
        )

    async def create_job(self, namespace: str, job: V1Job) -> V1Job:
        """Create a Job, returning the server-side object (with uid populated)."""
        return await asyncio.to_thread(
            self._batch.create_namespaced_job,
            namespace=namespace,
            body=job,
        )

    async def delete_job(self, namespace: str, name: str) -> None:
        """Delete a Job (and, via propagation, its Pods + owned PVCs).

        This is the *only* delete in Poiesis. PVC garbage collection happens
        automatically through the PVC's `ownerReferences` pointing at the
        Job — kube-controller-manager handles it.
        """
        await asyncio.to_thread(
            self._batch.delete_namespaced_job,
            name=name,
            namespace=namespace,
            propagation_policy="Background",
        )
