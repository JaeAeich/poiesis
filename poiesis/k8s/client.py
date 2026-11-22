"""Async-friendly wrapper over the synchronous kubernetes Python client."""

from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from urllib3.exceptions import HTTPError

from poiesis.errors import PoiesisError

if TYPE_CHECKING:
    from collections.abc import Callable

    from kubernetes.client import V1Job, V1PersistentVolumeClaim

logger = logging.getLogger(__name__)

#: (connect, read) timeouts of every Kubernetes call the API makes, so a
#: slow API server fails the request instead of holding a worker thread.
#: The read timeout covers admission webhooks, which Kubernetes lets run
#: for up to 30 seconds.
_REQUEST_TIMEOUT_SECONDS = (5, 30)


class K8sError(PoiesisError):
    """A Kubernetes call failed. The only error `K8sClient` raises."""


class K8sUnreachableError(K8sError):
    """The Kubernetes API didn't answer: a timeout or a connection failure.

    Unlike a `K8sRejectedError`, the call may have taken effect: a create
    that timed out may still have created the object.
    """


class K8sRejectedError(K8sError):
    """The Kubernetes API answered with an error; the call had no effect.

    Attributes:
        status: The HTTP status of the answer.
        reason: Its reason phrase, such as ``Forbidden``.
        body: Its body, which names the cause (a quota, a webhook).
    """

    def __init__(self, status: int, reason: str = "", body: str = "") -> None:
        """Keep what the API server answered."""
        super().__init__(f"({status}) {reason}".strip())
        self.status = status
        self.reason = reason
        self.body = body

    @property
    def not_found(self) -> bool:
        """Whether the object, or its namespace, doesn't exist."""
        return self.status == HTTPStatus.NOT_FOUND


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
    `asyncio.to_thread`, with a request timeout; a call the API server
    doesn't answer raises `K8sUnreachableError`, an error it answers with
    raises `K8sRejectedError`. The wrapper holds no per-call state — instances are cheap and safe to share across
    requests.
    """

    def __init__(self) -> None:
        """Build the BatchV1/CoreV1 API clients. Requires `load_config()` first."""
        self._batch = client.BatchV1Api()
        self._core = client.CoreV1Api()

    async def create_pvc(
        self, namespace: str, pvc: V1PersistentVolumeClaim
    ) -> V1PersistentVolumeClaim:
        """Create a PVC, returning the server-side object (with uid populated)."""
        return await _call(
            self._core.create_namespaced_persistent_volume_claim,
            namespace=namespace,
            body=pvc,
        )

    async def create_job(self, namespace: str, job: V1Job) -> V1Job:
        """Create a Job, returning the server-side object (with uid populated)."""
        return await _call(
            self._batch.create_namespaced_job,
            namespace=namespace,
            body=job,
        )

    async def delete_job(self, namespace: str, name: str) -> None:
        """Delete a Job (and, via propagation, its Pods + owned PVCs).

        This is the *only* delete in Poiesis. PVC garbage collection happens
        automatically through the PVC's `ownerReferences` pointing at the
        Job — kube-controller-manager handles it.

        Deleting a Job that is already gone succeeds.
        """
        try:
            await _call(
                self._batch.delete_namespaced_job,
                name=name,
                namespace=namespace,
                propagation_policy="Background",
            )
        except K8sRejectedError as exc:
            if not exc.not_found:
                raise


async def _call(method: Callable[..., Any], **kwargs: Any) -> Any:
    """Run a client call in a worker thread, with the request timeout.

    Raises `K8sUnreachableError` when the API server doesn't answer in time
    or can't be reached, `K8sRejectedError` when it answers with an error.
    """
    try:
        return await asyncio.to_thread(
            method, **kwargs, _request_timeout=_REQUEST_TIMEOUT_SECONDS
        )
    except HTTPError as exc:
        raise K8sUnreachableError(str(exc)) from exc
    except ApiException as exc:
        body = exc.body if isinstance(exc.body, str) else ""
        raise K8sRejectedError(exc.status or 0, exc.reason or "", body) from exc
