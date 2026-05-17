"""TES Task routes."""

import logging
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query
from kubernetes.client.exceptions import ApiException

from poiesis.api.deps import get_db_conn, get_k8s, get_runtime_config
from poiesis.api.exceptions import (
    APIError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    ServiceUnavailableError,
)
from poiesis.api.tes.models import (
    TesCancelTaskResponse,
    TesCreateTaskResponse,
    TesListTasksResponse,
    TesState,
    TesTask,
)
from poiesis.core.taskpod import (
    RuntimeConfig,
    attach_pvc_owner,
    build_taskpod_job,
    job_name_for,
)
from poiesis.db import state as state_db
from poiesis.db import tasks as tasks_db
from poiesis.db.tasks import ListFilters, TaskView
from poiesis.k8s import K8sClient

_MAX_PAGE_SIZE = 2048
_DEFAULT_PAGE_SIZE = 256

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
        created_job = await k8s.create_job(runtime_config.taskpod_namespace, job)
    except ApiException as exc:
        await _on_kubernetes_submit_failure(
            conn, task_id, exc, where="Job", k8s=None, namespace=None, job_name=None
        )

    job_uid, job_name = _server_assigned_meta(created_job)
    attach_pvc_owner(pvc, job_uid, job_name)

    try:
        await k8s.create_pvc(runtime_config.taskpod_namespace, pvc)
    except ApiException as exc:
        await _on_kubernetes_submit_failure(
            conn,
            task_id,
            exc,
            where="PVC",
            k8s=k8s,
            namespace=runtime_config.taskpod_namespace,
            job_name=job_name,
        )

    logger.info("TaskPod submitted for task %s (job=%s)", task_id, job_name)
    return TesCreateTaskResponse(id=task_id)


async def _on_kubernetes_submit_failure(
    conn: Any,
    task_id: str,
    exc: ApiException,
    *,
    where: str,
    k8s: K8sClient | None,
    namespace: str | None,
    job_name: str | None,
) -> None:
    """Classify a Kubernetes submit failure and raise the right APIError.

    Side effects, in order: log with traceback; best-effort delete the
    Job if we already created it; transition the task row to SYSTEM_ERROR
    with a useful reason; append the same reason to system_logs so it
    surfaces in GetTask / ListTasks output. This function always raises.
    """
    classification = _classify_submit_exception(exc, where)
    logger.exception(
        "%s submission failed for task %s (status=%s reason=%s)",
        where,
        task_id,
        exc.status,
        exc.reason,
    )
    if k8s is not None and namespace is not None and job_name is not None:
        await _safe_delete_job(k8s, namespace, job_name)

    await _mark_system_error(conn, task_id, classification.system_log)
    raise classification.api_error from exc


@dataclass(frozen=True)
class _SubmitErrorClassification:
    """How the API should respond to a submission failure.

    ``system_log`` is what gets persisted on the task row; ``api_error`` is
    raised on the request thread. Kept together so the two channels never
    drift on phrasing.
    """

    system_log: str
    api_error: APIError


def _classify_submit_exception(
    exc: ApiException, where: str
) -> _SubmitErrorClassification:
    """Map a Kubernetes ApiException to an HTTP response + system_logs entry.

    - 403 with quota messages → 503 Retry-After. The chart-shipped
    ResourceQuota is rejecting us; the client should back off.
    - 403 generic → 503 too; it's almost always RBAC + quota in practice
    and we'd rather over-classify retryable than under-classify it.
    - 422 from admission webhooks (SC missing, PVC malformed) → 400; the
    operator misconfigured the deployment but the client gets a clean
    error rather than a retry suggestion.
    - 404 on PVC create → 400 with "namespace missing" guidance.
    - Anything else → 500.
    """
    status = exc.status or 0
    body = (exc.body or "").lower() if isinstance(exc.body, str) else ""
    reason_lower = (exc.reason or "").lower()

    if status == HTTPStatus.FORBIDDEN.value or "forbidden" in reason_lower:
        if "exceeded quota" in body or "quota" in body:
            msg = f"{where} submission rejected: namespace quota exceeded"
            return _SubmitErrorClassification(
                system_log=msg,
                api_error=ServiceUnavailableError(msg, retry_after_seconds=30),
            )
        msg = f"{where} submission forbidden: {exc.reason}"
        return _SubmitErrorClassification(
            system_log=msg,
            api_error=ServiceUnavailableError(msg, retry_after_seconds=30),
        )

    if status == HTTPStatus.UNPROCESSABLE_ENTITY.value:
        if "storageclass" in body:
            msg = f"{where} submission failed: configured StorageClass not found"
        else:
            msg = f"{where} submission failed (validation): {exc.reason}"
        return _SubmitErrorClassification(
            system_log=msg, api_error=BadRequestError(msg)
        )

    if status == HTTPStatus.NOT_FOUND.value:
        msg = f"{where} submission failed: target namespace not found"
        return _SubmitErrorClassification(
            system_log=msg, api_error=BadRequestError(msg)
        )

    msg = f"{where} submission failed: {exc.reason}"
    return _SubmitErrorClassification(
        system_log=msg, api_error=InternalServerError(msg)
    )


@router.post(
    "/tasks/{id}:cancel",
    status_code=HTTPStatus.OK,
    operation_id="CancelTask",
)
async def cancel_task(
    id: str,
    conn: Annotated[Any, Depends(get_db_conn)],
    k8s: Annotated[K8sClient, Depends(get_k8s)],
    runtime_config: Annotated[RuntimeConfig, Depends(get_runtime_config)],
) -> TesCancelTaskResponse:
    """Mark the task CANCELING and delete its wrapping Kubernetes Job.

    TES treats cancel on a terminal task as a no-op success. The TaskPod
    self-finalises to CANCELED via TRec's SIGTERM handler; if TRec is dead,
    TCtl writes CANCELED when it observes the Pod terminate.
    """
    try:
        task_uuid = str(uuid.UUID(id))
    except ValueError as exc:
        raise BadRequestError(f"invalid task id: {id}") from exc

    if await tasks_db.get_task(conn, task_uuid, view=TaskView.MINIMAL) is None:
        raise NotFoundError(f"task {id} not found")

    transitioned = await state_db.mark_canceling(conn, task_uuid)
    if not transitioned:
        # Already terminal (or already CANCELING) — TES spec says return success.
        return TesCancelTaskResponse()

    try:
        await k8s.delete_job(runtime_config.taskpod_namespace, job_name_for(task_uuid))
    except ApiException as exc:
        if exc.status != HTTPStatus.NOT_FOUND:
            logger.exception("Job delete failed for task %s", task_uuid)
            raise InternalServerError("Failed to delete task Job") from exc

    return TesCancelTaskResponse()


@router.get(
    "/tasks/{id}",
    status_code=HTTPStatus.OK,
    operation_id="GetTask",
)
async def get_task(
    id: str,
    conn: Annotated[Any, Depends(get_db_conn)],
    view: Annotated[TaskView, Query()] = TaskView.MINIMAL,
) -> TesTask:
    """Return a single task at the requested view level."""
    try:
        task_uuid = str(uuid.UUID(id))
    except ValueError as exc:
        raise BadRequestError(f"invalid task id: {id}") from exc

    task = await tasks_db.get_task(conn, task_uuid, view=view)
    if task is None:
        raise NotFoundError(f"task {id} not found")
    return task


def _list_filters(
    name_prefix: Annotated[str | None, Query()] = None,
    state: Annotated[TesState | None, Query()] = None,
    tag_key: Annotated[list[str] | None, Query()] = None,
    tag_value: Annotated[list[str] | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
    page_token: Annotated[str | None, Query()] = None,
) -> ListFilters:
    """Bind the TES list-tasks query string into a `ListFilters` value."""
    return ListFilters(
        name_prefix=name_prefix,
        state=state,
        tag_key=tag_key or [],
        tag_value=tag_value or [],
        page_size=page_size,
        page_token=page_token,
    )


@router.get(
    "/tasks",
    status_code=HTTPStatus.OK,
    operation_id="ListTasks",
)
async def list_tasks(
    conn: Annotated[Any, Depends(get_db_conn)],
    filters: Annotated[ListFilters, Depends(_list_filters)],
    view: Annotated[TaskView, Query()] = TaskView.MINIMAL,
) -> TesListTasksResponse:
    """Return a paginated list of tasks, newest first."""
    try:
        tasks, next_token = await tasks_db.list_tasks(conn, filters, view=view)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return TesListTasksResponse(tasks=tasks, next_page_token=next_token)


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
    """Best-effort transition to SYSTEM_ERROR after a submission failure.

    Writes both the terminal state and a system_logs entry so the same
    diagnostic string is visible via ``GetTask`` for client inspection.
    """
    try:
        await state_db.write_terminal_state(
            conn, task_id, TesState.SYSTEM_ERROR, reason=reason
        )
        await state_db.append_system_log(conn, task_id, reason)
    except (asyncpg.PostgresError, OSError, TimeoutError):
        logger.exception(
            "Failed to mark task %s SYSTEM_ERROR after submission failure", task_id
        )


async def _safe_delete_job(k8s: K8sClient, namespace: str, name: str) -> None:
    """Best-effort Job cleanup after a failed PVC submission."""
    try:
        await k8s.delete_job(namespace, name)
    except ApiException:
        logger.warning("Job %s cleanup failed (non-fatal)", name)
