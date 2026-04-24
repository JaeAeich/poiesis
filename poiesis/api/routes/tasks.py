"""TES Task routes.

Implements `POST /tasks` (CreateTask).
"""

import logging
import uuid
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from kubernetes.client.exceptions import ApiException

from poiesis.api.deps import get_db_conn, get_k8s, get_runtime_config
from poiesis.api.exceptions import BadRequestError, InternalServerError
from poiesis.api.tes.models import (
    TesCreateTaskResponse,
    TesState,
    TesTask,
)
from poiesis.core.taskpod import RuntimeConfig, attach_pvc_owner, build_taskpod_job
from poiesis.db import state as state_db
from poiesis.db import tasks as tasks_db
from poiesis.k8s import K8sClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["TaskService"])


@router.post(
    "/tasks",
    status_code=HTTPStatus.OK,
    operation_id="CreateTask",
)
async def create_task(
    task: TesTask,
    conn: Annotated[Any, Depends(get_db_conn)],
    k8s: Annotated[K8sClient, Depends(get_k8s)],
    runtime_config: Annotated[RuntimeConfig, Depends(get_runtime_config)],
) -> TesCreateTaskResponse:
    """Accept a TES task, persist it, and submit its TaskPod to Kubernetes."""
    task.id = task.id or str(uuid.uuid4())
    task.state = TesState.QUEUED

    # Build the K8s manifests first so spec-builder errors (e.g.
    # ignore_error=True) surface as 400s before we write anything.
    try:
        pvc, job = build_taskpod_job(task, runtime_config)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc

    task_id = await tasks_db.create_task(conn, task)
    logger.info("Persisted task %s", task_id)

    # Submit the Job first; the Pod will wait Pending until the PVC exists.
    # The PVC is created with an ownerReference back to the Job so
    # kube-controller-manager garbage-collects it when the Job is deleted.
    try:
        created_job = await k8s.create_job(runtime_config.namespace, job)
    except ApiException as exc:
        logger.exception("Job submission failed for task %s", task_id)
        await _mark_system_error(conn, task_id, f"Job submission failed: {exc.reason}")
        raise InternalServerError("Failed to create task Job") from exc

    job_uid, job_name = _server_assigned_meta(created_job)
    attach_pvc_owner(pvc, job_uid, job_name)

    try:
        await k8s.create_pvc(runtime_config.namespace, pvc)
    except ApiException as exc:
        logger.exception("PVC submission failed for task %s; deleting Job", task_id)
        await _safe_delete_job(k8s, runtime_config.namespace, job_name)
        await _mark_system_error(conn, task_id, f"PVC submission failed: {exc.reason}")
        raise InternalServerError("Failed to create task PVC") from exc

    logger.info("TaskPod submitted for task %s (job=%s)", task_id, job_name)
    return TesCreateTaskResponse(id=task_id)


def _server_assigned_meta(obj: Any) -> tuple[str, str]:
    """Return (uid, name) from a server-returned K8s object.

    The fields are typed Optional but the K8s API server always populates
    them on successful creation; pulling them out once and asserting here
    keeps the rest of the handler free of `.metadata.uid` chains.
    """
    metadata = obj.metadata
    if metadata is None or metadata.uid is None or metadata.name is None:
        msg = "Kubernetes returned an object without populated metadata"
        raise InternalServerError(msg)
    return metadata.uid, metadata.name


async def _mark_system_error(conn: Any, task_id: str, reason: str) -> None:
    """Best-effort transition to SYSTEM_ERROR after a submission failure."""
    try:
        await state_db.write_terminal_state(
            conn, task_id, TesState.SYSTEM_ERROR, reason=reason
        )
    except Exception:
        logger.exception(
            "Failed to mark task %s SYSTEM_ERROR after submission failure", task_id
        )


async def _safe_delete_job(k8s: K8sClient, namespace: str, name: str) -> None:
    """Best-effort Job cleanup after a failed PVC submission."""
    try:
        await k8s.delete_job(namespace, name)
    except ApiException:
        logger.warning("Job %s cleanup failed (non-fatal)", name)
