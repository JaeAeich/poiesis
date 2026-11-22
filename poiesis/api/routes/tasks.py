"""TES Task routes."""

import logging
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, Any, NoReturn

import asyncpg
from fastapi import APIRouter, Depends, Query

from poiesis.api.auth import Principal
from poiesis.api.authz import Authz, get_authz, task_reader, task_writer
from poiesis.api.deps import get_db_pool, get_k8s, get_runtime_config
from poiesis.api.exceptions import (
    APIError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    ServiceUnavailableError,
)
from poiesis.api.metrics import SubmitOutcome, count_submission
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
from poiesis.k8s import K8sClient, K8sError, K8sRejectedError, K8sUnreachableError

_MAX_PAGE_SIZE = 2048
_DEFAULT_PAGE_SIZE = 256

logger = logging.getLogger(__name__)

router = APIRouter(tags=["TaskService"])


@router.post(
    "/tasks",
    status_code=HTTPStatus.OK,
    operation_id="CreateTask",
    # Omit unset fields: TES clients such as py-tes (Snakemake, cwl-tes)
    # can't parse `null` where an object or list is expected.
    response_model_exclude_none=True,
)
async def create_task(
    task: TesTask,
    k8s: Annotated[K8sClient, Depends(get_k8s)],
    runtime_config: Annotated[RuntimeConfig, Depends(get_runtime_config)],
    principal: Annotated[Principal, Depends(task_writer)],
    authz: Annotated[Authz, Depends(get_authz)],
    pool: Annotated[Any, Depends(get_db_pool)],
) -> TesCreateTaskResponse:
    """Accept a TES task, persist it, and submit its TaskPod to Kubernetes."""
    # Server-assigned fields: a client-chosen id would reveal whether a
    # task with that id exists.
    task = task.model_copy(
        update={
            "id": str(uuid.uuid4()),
            "state": TesState.QUEUED,
            "logs": None,
            "creation_time": TesTask.model_fields["creation_time"].get_default(
                call_default_factory=True
            ),
        }
    )
    groups = await authz.check_create(principal, task)

    # Build the K8s manifests first so spec-builder errors (e.g. an
    # unsupported input URL scheme) surface as 400s before we write anything.
    try:
        pvc, job = build_taskpod_job(task, runtime_config)
    except ValueError as exc:
        count_submission(SubmitOutcome.REJECTED)
        raise BadRequestError(str(exc)) from exc

    # Acquired only after the decision, so it never waits holding one, and
    # given back before the Kubernetes calls, so a slow API server can't
    # drain the pool.
    async with pool.acquire() as conn:
        task_id = await tasks_db.create_task(conn, task, principal.owner, groups)
    logger.info("Persisted task %s", task_id)

    # Submit the Job first; the Pod will wait Pending until the PVC exists.
    # The PVC is created with an ownerReference back to the Job so
    # kube-controller-manager garbage-collects it when the Job is deleted.
    namespace = runtime_config.taskpod_namespace
    try:
        created_job = await k8s.create_job(namespace, job)
    except K8sError as exc:
        # No answer: the Job may have been created all the same.
        job_may_exist = isinstance(exc, K8sUnreachableError)
        await _fail_submission(
            pool,
            task_id,
            exc,
            where="Job",
            delete_job=_JobRef(k8s, namespace, job_name_for(task_id))
            if job_may_exist
            else None,
        )

    job_uid, job_name = _server_assigned_meta(created_job)
    attach_pvc_owner(pvc, job_uid, job_name)

    try:
        await k8s.create_pvc(namespace, pvc)
    except K8sError as exc:
        await _fail_submission(
            pool,
            task_id,
            exc,
            where="PVC",
            delete_job=_JobRef(k8s, namespace, job_name),
        )

    logger.info("TaskPod submitted for task %s (job=%s)", task_id, job_name)
    count_submission(SubmitOutcome.CREATED)
    return TesCreateTaskResponse(id=task_id)


@dataclass(frozen=True)
class _JobRef:
    """A Job that may exist and where to delete it."""

    k8s: K8sClient
    namespace: str
    name: str


async def _fail_submission(
    pool: Any,
    task_id: str,
    exc: K8sError,
    *,
    where: str,
    delete_job: _JobRef | None,
) -> NoReturn:
    """Classify a Kubernetes submit failure and raise the right APIError.

    Side effects, in order: log with traceback; best-effort delete the
    Job if we already created it; transition the task row to SYSTEM_ERROR
    with a useful reason; append the same reason to system_logs so it
    surfaces in GetTask / ListTasks output. This function always raises.
    """
    count_submission(SubmitOutcome.SUBMIT_FAILED)
    classification = _classify_submit_exception(exc, where)
    logger.exception(
        "%s submission failed for task %s (status=%s reason=%s)",
        where,
        task_id,
        getattr(exc, "status", None),
        getattr(exc, "reason", exc),
    )
    if delete_job is not None:
        await _delete_job_best_effort(delete_job)

    await _mark_system_error(pool, task_id, classification.system_log)
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


def _classify_submit_exception(exc: K8sError, where: str) -> _SubmitErrorClassification:
    """Map a Kubernetes failure to an HTTP response + system_logs entry.

    - 403 with quota messages → 503 Retry-After. The chart-shipped
    ResourceQuota is rejecting us; the client should back off.
    - 403 generic → 503 too; it's almost always RBAC + quota in practice
    and we'd rather over-classify retryable than under-classify it.
    - 422 from admission webhooks (SC missing, PVC malformed) → 400; the
    operator misconfigured the deployment but the client gets a clean
    error rather than a retry suggestion.
    - 404 on PVC create → 400 with "namespace missing" guidance.
    - No answer (timeout, connection failure) → 503 Retry-After.
    - Anything else → 500.
    """
    if not isinstance(exc, K8sRejectedError):
        msg = f"{where} submission failed: Kubernetes API did not answer"
        return _SubmitErrorClassification(
            system_log=msg,
            api_error=ServiceUnavailableError(msg, retry_after_seconds=30),
        )
    status = exc.status
    body = exc.body.lower()
    reason_lower = exc.reason.lower()

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
    response_model_exclude_none=True,
)
async def cancel_task(
    id: str,
    k8s: Annotated[K8sClient, Depends(get_k8s)],
    runtime_config: Annotated[RuntimeConfig, Depends(get_runtime_config)],
    principal: Annotated[Principal, Depends(task_writer)],
    authz: Annotated[Authz, Depends(get_authz)],
    pool: Annotated[Any, Depends(get_db_pool)],
) -> TesCancelTaskResponse:
    """Mark the task CANCELING and delete its wrapping Kubernetes Job.

    TES treats cancel on a terminal task as a no-op success. This route
    never writes `CANCELED`, and neither does TRec: TCtl is the single
    writer of terminal state. With the Job deleted the Pod disappears;
    TCtl's orphan pass finds the task without a Job or Pod and proposes
    `SYSTEM_ERROR`, which the writer's `CANCELING` precedence lands as
    `CANCELED`. A Pod that reaches a terminal phase first lands as
    `CANCELED` the same way. If the delete here fails, TCtl deletes the
    Job of the `CANCELING` task on its next pass.
    """
    task_uuid = _parse_task_id(id)

    async with pool.acquire() as conn:
        meta = await tasks_db.get_task_meta(conn, task_uuid)
    await authz.check_cancel(principal, task_uuid, meta)

    async with pool.acquire() as conn:
        transitioned = await state_db.mark_canceling(conn, task_uuid)
        if not transitioned:
            current = await tasks_db.get_task_meta(conn, task_uuid)
            if current is None or current["state"] != TesState.CANCELING.value:
                # Already terminal — TES spec says return success.
                return TesCancelTaskResponse()

    # Also when the task was CANCELING already: an earlier cancel may have
    # failed to delete the Job, or the Job was created after it. The delete
    # is idempotent, so repeating it is safe.

    try:
        await k8s.delete_job(runtime_config.taskpod_namespace, job_name_for(task_uuid))
    except K8sError as exc:
        logger.exception("Job delete failed for task %s", task_uuid)
        raise InternalServerError("Failed to delete task Job") from exc

    return TesCancelTaskResponse()


@router.get(
    "/tasks/{id}",
    status_code=HTTPStatus.OK,
    operation_id="GetTask",
    response_model_exclude_none=True,
)
async def get_task(
    id: str,
    principal: Annotated[Principal, Depends(task_reader)],
    authz: Annotated[Authz, Depends(get_authz)],
    pool: Annotated[Any, Depends(get_db_pool)],
    view: Annotated[TaskView, Query()] = TaskView.MINIMAL,
) -> TesTask:
    """Return a single task at the requested view level."""
    task_uuid = _parse_task_id(id)

    async with pool.acquire() as conn:
        meta = await tasks_db.get_task_meta(conn, task_uuid)
    allowed = await authz.may_read(principal, task_uuid, meta, view.value)
    task = None
    if allowed:
        async with pool.acquire() as conn:
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
    response_model_exclude_none=True,
)
async def list_tasks(
    filters: Annotated[ListFilters, Depends(_list_filters)],
    principal: Annotated[Principal, Depends(task_reader)],
    authz: Annotated[Authz, Depends(get_authz)],
    pool: Annotated[Any, Depends(get_db_pool)],
    view: Annotated[TaskView, Query()] = TaskView.MINIMAL,
) -> TesListTasksResponse:
    """Return a paginated list of tasks, newest first."""
    filters.owner, filters.scope = await authz.visible_tasks(principal, view.value)
    try:
        async with pool.acquire() as conn:
            tasks, next_token = await tasks_db.list_tasks(conn, filters, view=view)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return TesListTasksResponse(tasks=tasks, next_page_token=next_token)


def _parse_task_id(id: str) -> str:
    """Return the task id in canonical form; a ``400`` if it isn't a UUID."""
    try:
        return str(uuid.UUID(id))
    except ValueError as exc:
        raise BadRequestError(f"invalid task id: {id}") from exc


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


async def _mark_system_error(pool: Any, task_id: str, reason: str) -> None:
    """Best-effort transition to SYSTEM_ERROR after a submission failure.

    Writes both the terminal state and a system_logs entry so the same
    diagnostic string is visible via ``GetTask`` for client inspection.
    Takes a pooled connection only for these writes, after the Kubernetes
    calls (and the Job cleanup) are done.
    """
    try:
        async with pool.acquire() as conn:
            await state_db.write_terminal_state(
                conn, task_id, TesState.SYSTEM_ERROR, reason=reason
            )
            await state_db.append_system_log(conn, task_id, reason)
    except (asyncpg.PostgresError, OSError, TimeoutError):
        logger.exception(
            "Failed to mark task %s SYSTEM_ERROR after submission failure", task_id
        )


async def _delete_job_best_effort(job: _JobRef) -> None:
    """Job cleanup after a failed submission; a failure is only logged."""
    try:
        await job.k8s.delete_job(job.namespace, job.name)
    except K8sError:
        logger.warning("Job %s cleanup failed (non-fatal)", job.name)
