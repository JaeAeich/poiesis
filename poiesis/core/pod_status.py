"""Pod status → task event translation.

A pure function that takes a Kubernetes Pod status snapshot and the task
state previously observed by the caller, and emits a list of structured
events describing what changed.

Used by both the in-Pod recorder (per watch event during the Pod's life)
and the global controller (once, on Pod terminal events). The function
has no I/O — it operates only on the data shape kubelet publishes, so
every failure mode is a fixture and the test surface is exhaustively
enumerable.

Container naming convention (also enforced by the spec builder):

    trec        the recorder native sidecar
    tif         the input filer
    exec-{N}    the N-th executor, zero-indexed
    tof         the output filer
    ack         the regular main container — runs after every init
                container finishes and exits 0 so the Pod reaches Succeeded
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from poiesis.core import filer_error, ignore_error
from poiesis.tes.models import TesState

if TYPE_CHECKING:
    from collections.abc import Mapping

_EXECUTOR_RE = re.compile(r"^exec-(\d+)$")

TREC_NAME = "trec"
TIF_NAME = "tif"
TOF_NAME = "tof"
ACK_NAME = "ack"


class ContainerKind(Enum):
    """Logical role of a container in the TaskPod."""

    TREC = "trec"
    TIF = "tif"
    EXECUTOR = "executor"
    TOF = "tof"
    ACK = "ack"
    UNKNOWN = "unknown"


class PodTerminationReason(Enum):
    """Why the Pod terminated, when termination is observed via the Pod object."""

    COMPLETED = "Completed"
    # An executor over its memory limit; a poiesis-owned container (trec,
    # tif, tof, ack) over its own is SYSTEM_OOM_KILLED.
    OOM_KILLED = "OOMKilled"
    SYSTEM_OOM_KILLED = "SystemOOMKilled"
    EVICTED = "Evicted"
    NODE_LOST = "NodeLost"
    DEADLINE_EXCEEDED = "DeadlineExceeded"
    PVC_BIND_FAILURE = "PVCBindFailure"
    FILER_ERROR = "FilerError"
    ERROR = "Error"
    UNKNOWN = "Unknown"


class EventKind(Enum):
    """The kinds of transitions the translator can emit."""

    TIF_STARTED = "tif_started"
    TIF_FINISHED = "tif_finished"
    EXECUTOR_STARTED = "executor_started"
    EXECUTOR_FINISHED = "executor_finished"
    TOF_STARTED = "tof_started"
    TOF_FINISHED = "tof_finished"
    POD_TERMINATED = "pod_terminated"


@dataclass(frozen=True)
class TaskEvent:
    """A single transition observed in the Pod since the previous snapshot.

    Attributes:
        kind: Which transition this is.
        executor_index: Set for EXECUTOR_* events; the zero-indexed executor ordinal.
        exit_code: Set for *_FINISHED and POD_TERMINATED events when known.
        reason: Set for *_FINISHED with non-zero exit and for POD_TERMINATED.
        started_at: ISO-8601 timestamp string, when known.
        finished_at: ISO-8601 timestamp string, when known.
    """

    kind: EventKind
    executor_index: int | None = None
    exit_code: int | None = None
    reason: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class TaskStateSnapshot:
    """What the caller has already recorded for this task.

    The translator emits only events that move *past* this snapshot —
    e.g. if `tif_finished` is True, no TIF events are re-emitted even if
    they're present in the Pod status.
    """

    tif_finished: bool = False
    executors_finished: frozenset[int] = frozenset()
    tof_finished: bool = False
    pod_terminated: bool = False
    #: Set by trec once it wrote RUNNING; the translator ignores it.
    running: bool = False


def classify_container(name: str) -> tuple[ContainerKind, int | None]:
    """Return the role of a container by name + executor index when applicable."""
    if name == TREC_NAME:
        return ContainerKind.TREC, None
    if name == TIF_NAME:
        return ContainerKind.TIF, None
    if name == TOF_NAME:
        return ContainerKind.TOF, None
    if name == ACK_NAME:
        return ContainerKind.ACK, None
    m = _EXECUTOR_RE.match(name)
    if m:
        return ContainerKind.EXECUTOR, int(m.group(1))
    return ContainerKind.UNKNOWN, None


def translate(
    pod_status: Mapping[str, Any],
    previous: TaskStateSnapshot,
) -> list[TaskEvent]:
    """Translate a Pod.status snapshot into a list of new task events.

    Args:
        pod_status: A dict matching the shape of `kubernetes.client.V1PodStatus`'s
            JSON serialization (camelCase keys). Either passing the model's
            `.to_dict()` or a raw watch-event payload works.
        previous: What the caller already recorded; events that have already
            been emitted are filtered out.

    Returns:
        A list of new events, ordered by the lifecycle phase they describe
        (TIF first, then executors in order, then TOF, then any pod-level
        termination).
    """
    by_kind = _group_init_containers(pod_status)
    events: list[TaskEvent] = []
    events.extend(_tif_events(by_kind, previous))
    events.extend(_executor_events(by_kind, previous))
    events.extend(_tof_events(by_kind, previous))
    if not previous.pod_terminated:
        pod_event = _pod_terminated_event(pod_status)
        if pod_event is not None:
            events.append(pod_event)
    return events


def _group_init_containers(
    pod_status: Mapping[str, Any],
) -> dict[ContainerKind, list[tuple[int | None, dict[str, Any]]]]:
    """Group init container statuses by their classified role."""
    init_statuses = (
        pod_status.get("initContainerStatuses")
        or pod_status.get("init_container_statuses")
        or []
    )
    by_kind: dict[ContainerKind, list[tuple[int | None, dict[str, Any]]]] = {}
    for cs in init_statuses:
        kind, idx = classify_container(cs.get("name", ""))
        by_kind.setdefault(kind, []).append((idx, cs))
    return by_kind


def _tif_events(
    by_kind: dict[ContainerKind, list[tuple[int | None, dict[str, Any]]]],
    previous: TaskStateSnapshot,
) -> list[TaskEvent]:
    """Events for the input filer, if any."""
    if previous.tif_finished:
        return []
    out: list[TaskEvent] = []
    for _, cs in by_kind.get(ContainerKind.TIF, []):
        ev = _container_finished_event(
            cs, EventKind.TIF_STARTED, EventKind.TIF_FINISHED
        )
        if ev is not None:
            out.append(ev)
    return out


def _tof_events(
    by_kind: dict[ContainerKind, list[tuple[int | None, dict[str, Any]]]],
    previous: TaskStateSnapshot,
) -> list[TaskEvent]:
    """Events for the output filer, if any."""
    if previous.tof_finished:
        return []
    out: list[TaskEvent] = []
    for _, cs in by_kind.get(ContainerKind.TOF, []):
        ev = _container_finished_event(
            cs, EventKind.TOF_STARTED, EventKind.TOF_FINISHED
        )
        if ev is not None:
            out.append(ev)
    return out


def _executor_events(
    by_kind: dict[ContainerKind, list[tuple[int | None, dict[str, Any]]]],
    previous: TaskStateSnapshot,
) -> list[TaskEvent]:
    """Events for each executor not already finished, in submission order."""
    out: list[TaskEvent] = []
    for idx, cs in sorted(
        by_kind.get(ContainerKind.EXECUTOR, []),
        key=lambda pair: pair[0] if pair[0] is not None else -1,
    ):
        if idx is None or idx in previous.executors_finished:
            continue
        ev = _container_finished_event(
            cs,
            EventKind.EXECUTOR_STARTED,
            EventKind.EXECUTOR_FINISHED,
            executor_index=idx,
        )
        if ev is not None:
            out.append(ev)
    return out


def _container_finished_event(
    container_status: dict[str, Any],
    started_kind: EventKind,
    finished_kind: EventKind,
    executor_index: int | None = None,
) -> TaskEvent | None:
    """Emit a Started or Finished event for a single container, or None.

    Returns None when the container has not started yet, or when it is
    still running. Started events are emitted when the container is
    running but not yet terminated; Finished events when terminated.
    """
    state = container_status.get("state") or {}
    terminated = state.get("terminated")
    if terminated is not None:
        exit_code = terminated.get("exitCode")
        if exit_code is None:
            exit_code = terminated.get("exit_code")
        if executor_index is not None:
            # An ignore_error executor exits 0 and reports the command's
            # exit code in its termination message.
            exit_code = ignore_error.recorded_exit_code(terminated)
        reason = terminated.get("reason")
        started_at = terminated.get("startedAt") or terminated.get("started_at")
        finished_at = terminated.get("finishedAt") or terminated.get("finished_at")
        return TaskEvent(
            kind=finished_kind,
            executor_index=executor_index,
            exit_code=exit_code,
            reason=reason if exit_code != 0 else None,
            started_at=str(started_at) if started_at is not None else None,
            finished_at=str(finished_at) if finished_at is not None else None,
        )
    running = state.get("running")
    if running is not None:
        started_at = running.get("startedAt") or running.get("started_at")
        return TaskEvent(
            kind=started_kind,
            executor_index=executor_index,
            started_at=str(started_at) if started_at is not None else None,
        )
    return None


def _pod_terminated_event(pod_status: Mapping[str, Any]) -> TaskEvent | None:
    """Detect a Pod-level termination event.

    Recognises:
        - phase == 'Succeeded' / 'Failed' (kubelet has finalised)
        - reason == 'Evicted' / 'NodeLost' / 'DeadlineExceeded'
        - condition `PodScheduled` False with reason `Unschedulable` past grace
        (handled by the caller via deadline policy; we just surface it)

    Returns None if the Pod is still running.
    """
    phase = pod_status.get("phase")
    if phase not in {"Succeeded", "Failed"}:
        return None

    pod_reason = pod_status.get("reason") or ""

    # Look for a container-level OOMKilled — kubelet sets phase=Failed with
    # the container reason embedded in initContainerStatuses or
    # containerStatuses.
    container_reasons = _collect_container_reasons(pod_status)

    if "OOMKilled" in container_reasons:
        reason = PodTerminationReason.OOM_KILLED.value
    elif pod_reason == "Evicted":
        reason = PodTerminationReason.EVICTED.value
    elif pod_reason == "NodeLost":
        reason = PodTerminationReason.NODE_LOST.value
    elif pod_reason == "DeadlineExceeded":
        reason = PodTerminationReason.DEADLINE_EXCEEDED.value
    elif phase == "Succeeded":
        reason = PodTerminationReason.COMPLETED.value
    elif container_reasons:
        # Fall back to the first non-empty container reason for context.
        reason = next(iter(container_reasons), PodTerminationReason.ERROR.value)
    else:
        reason = PodTerminationReason.ERROR.value

    return TaskEvent(kind=EventKind.POD_TERMINATED, reason=reason)


def pod_terminated_terminal(
    pod_reason: str | None,
) -> tuple[TesState, str | None]:
    """Map a Pod-termination reason to a terminal TES state + reason string.

    A failed filer (`FILER_ERROR`) is a system error: the executors didn't
    fail, staging their inputs or outputs did. An executor killed for
    exceeding its memory (`OOM_KILLED`) is an executor error: the task
    asked for less memory than it uses (``resources.ram_gb``).
    """
    if pod_reason == PodTerminationReason.COMPLETED.value:
        return TesState.COMPLETE, None
    if pod_reason in {
        PodTerminationReason.SYSTEM_OOM_KILLED.value,
        PodTerminationReason.EVICTED.value,
        PodTerminationReason.NODE_LOST.value,
        PodTerminationReason.DEADLINE_EXCEEDED.value,
        PodTerminationReason.PVC_BIND_FAILURE.value,
        PodTerminationReason.FILER_ERROR.value,
    }:
        return TesState.SYSTEM_ERROR, pod_reason
    return TesState.EXECUTOR_ERROR, pod_reason


def job_deadline_terminal(
    job: Mapping[str, Any],
) -> tuple[TesState, str, str] | None:
    """Terminal state, reason and system log line for a Job past its deadline.

    When a Job's `activeDeadlineSeconds` runs out, the Job controller
    deletes the Pod and sets a `Failed` condition with reason
    `DeadlineExceeded` on the Job (newer clusters set `FailureTarget`
    first, while the Pod is still terminating). The Pod itself carries no
    such reason: it is gone, or seen `Failed` with a killed executor. So
    the Job is the only place the cause can be read.

    Args:
        job: A Job as a dict, from `to_dict()` (snake_case) or a raw
            payload (camelCase).

    Returns:
        `(SYSTEM_ERROR, "DeadlineExceeded", log line)` when the Job hit its
        deadline, else None.
    """
    conditions = (job.get("status") or {}).get("conditions") or []
    if not any(
        cond.get("type") in {"Failed", "FailureTarget"}
        and str(cond.get("status")) == "True"
        and cond.get("reason") == PodTerminationReason.DEADLINE_EXCEEDED.value
        for cond in conditions
    ):
        return None
    spec = job.get("spec") or {}
    seconds = spec.get("active_deadline_seconds", spec.get("activeDeadlineSeconds"))
    line = "task exceeded its time limit"
    if seconds is not None:
        line += f" of {seconds} seconds"
    return TesState.SYSTEM_ERROR, PodTerminationReason.DEADLINE_EXCEEDED.value, line


def extract_terminal_reason(pod: Mapping[str, Any]) -> str | None:
    """Map a Pod's status to one of `PodTerminationReason.*.value`.

    Reads the Pod-level `status.reason` first (NodeLost, Evicted,
    DeadlineExceeded all surface here), falls back to scanning container
    terminated states for a more specific reason. Skips containers that
    completed (exit 0: trec, a filer, an earlier executor, `ack`), and trec
    or `ack` stopped as the Pod ends (`is_lifecycle_stop`), so they don't
    shadow the underlying error of a failed Pod.

    A filer (tif, tof) that failed gives `FILER_ERROR`, unless it was
    OOMKilled, or reported that the failure is the user's
    (`is_filer_failure`), which leaves the container's own reason. An
    OOMKilled executor gives `OOM_KILLED`, any other OOMKilled container
    `SYSTEM_OOM_KILLED`.
    """
    status = pod.get("status") or {}
    raw_reason = status.get("reason")
    if raw_reason == "Evicted":
        return PodTerminationReason.EVICTED.value
    if raw_reason == "NodeLost":
        return PodTerminationReason.NODE_LOST.value
    if raw_reason == "DeadlineExceeded":
        return PodTerminationReason.DEADLINE_EXCEEDED.value
    if status.get("phase") == "Succeeded":
        return PodTerminationReason.COMPLETED.value

    for cs in _iter_container_statuses(status):
        terminated = (cs.get("state") or {}).get("terminated") or {}
        exit_code = terminated.get("exitCode", terminated.get("exit_code"))
        cs_reason = terminated.get("reason")
        if exit_code == 0 or cs_reason == PodTerminationReason.COMPLETED.value:
            continue
        if is_lifecycle_stop(status, cs.get("name") or "", terminated):
            continue
        cs_reason = _failure_reason(cs.get("name") or "", terminated)
        if cs_reason:
            return cs_reason
    return PodTerminationReason.ERROR.value


def _failure_reason(name: str, terminated: Mapping[str, Any]) -> str | None:
    """The task's reason for container `name`, which failed.

    `FILER_ERROR` for a filer failure that is the system's, `SYSTEM_OOM_KILLED`
    for an OOMKilled container that isn't an executor, else its own reason.
    """
    if is_filer_failure(name, terminated):
        return PodTerminationReason.FILER_ERROR.value
    reason = terminated.get("reason")
    if reason == PodTerminationReason.OOM_KILLED.value and not _EXECUTOR_RE.match(name):
        return PodTerminationReason.SYSTEM_OOM_KILLED.value
    return str(reason) if reason else None


def is_filer_failure(name: str, terminated: Mapping[str, Any]) -> bool:
    """True if `name` is a filer whose failure is the system's.

    That is tif or tof exiting non-zero for any reason but two. An
    OOMKilled filer is reported as OOMKilled. A filer whose termination
    message says the user is at fault, as tof's does for a declared output
    the executors didn't produce, failed as an executor would have.
    """
    if name not in (TIF_NAME, TOF_NAME):
        return False
    if ignore_error.terminated_exit_code(terminated) in (None, 0):
        return False
    if terminated.get("reason") == PodTerminationReason.OOM_KILLED.value:
        return False
    cause = filer_error.cause(terminated)
    return cause is None or not cause[1]


def filer_failure_log(name: str, terminated: Mapping[str, Any]) -> str | None:
    """System log line for a filer that failed and said why.

    Returns None for other containers and for a filer that left no cause
    in its termination message.
    """
    if name not in (TIF_NAME, TOF_NAME):
        return None
    exit_code = ignore_error.terminated_exit_code(terminated)
    cause = filer_error.cause(terminated)
    if exit_code in (None, 0) or cause is None:
        return None
    return f"container {name} exited with code {exit_code}: {cause[0]}"


def is_lifecycle_stop(
    pod_status: Mapping[str, Any], name: str, terminated: Mapping[str, Any]
) -> bool:
    """True if `name`, trec or `ack`, ended because the Pod did, not on its own.

    The kubelet stops trec, a native sidecar, once the other containers have
    ended (and SIGKILLs it, exit 137, if it outlives the grace period);
    `ack` only starts after the work. Either one's exit is a failure only
    if it ended before the work containers (tif, the executors, tof) did:
    trec dying mid-task. Without the timestamps to tell, it counts as one.
    """
    if name not in (TREC_NAME, ACK_NAME):
        return False
    ended = parse_timestamp(
        terminated.get("finishedAt") or terminated.get("finished_at")
    )
    work_ended = [
        parse_timestamp(t.get("finishedAt") or t.get("finished_at"))
        for cs in _iter_container_statuses(pod_status)
        if classify_container(cs.get("name") or "")[0]
        in (ContainerKind.TIF, ContainerKind.EXECUTOR, ContainerKind.TOF)
        and (t := (cs.get("state") or {}).get("terminated"))
    ]
    if ended is None or not work_ended or None in work_ended:
        return False
    return ended >= max(w for w in work_ended if w is not None)


def parse_timestamp(value: object) -> datetime | None:
    """A Kubernetes timestamp: a datetime (``to_dict()``) or ISO-8601 string.

    None for a missing or unreadable value.
    """
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def created_at(obj: Mapping[str, Any]) -> datetime | None:
    """`metadata.creationTimestamp` of a Pod or Job, made timezone-aware."""
    metadata = obj.get("metadata") or {}
    created = parse_timestamp(
        metadata.get("creationTimestamp") or metadata.get("creation_timestamp")
    )
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created


def extract_job_failure(job: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Whether a Job has finished, and why it failed if it did.

    Returns `(finished, failure)`: `finished` is True once the Job carries
    a `Complete` or `Failed` condition; `failure` is the `Failed`
    condition's `reason: message` (e.g. `BackoffLimitExceeded: Job has
    reached the specified backoff limit`), None for a Job that didn't fail.
    A Job past its time limit fails too; `job_deadline_terminal` gives it
    its own state and log line, so callers check that first.
    """
    finished = False
    for cond in (job.get("status") or {}).get("conditions") or []:
        if cond.get("status") != "True":
            continue
        if cond.get("type") == "Failed":
            reason = str(cond.get("reason") or "Failed")
            message = cond.get("message")
            return True, f"{reason}: {message}" if message else reason
        if cond.get("type") == "Complete":
            finished = True
    return finished, None


def extract_pending_failure_reason(pod: Mapping[str, Any]) -> str:
    """Best-effort human-readable cause for a stuck-Pending Pod.

    Order of preference (most specific first):

    1. Container-level waiting reasons that aren't transient (image pull
        failures, config errors).
    2. Storage-side scheduling failures: the scheduler emits the
        specifics inside ``PodScheduled``/``False``.message. We classify
        the common ones (StorageClass missing, volume zone mismatch,
        quota exceeded) into stable strings so operators can grep logs.
    3. Generic ``PodScheduled``/``False``.reason.
    4. Fallback ``"Pending timeout"``.
    """
    status = pod.get("status") or {}

    for cs in _iter_container_statuses(status):
        waiting = (cs.get("state") or {}).get("waiting") or {}
        reason = waiting.get("reason")
        if reason and reason not in {"PodInitializing", "ContainerCreating"}:
            return str(reason)

    for cond in status.get("conditions") or []:
        if cond.get("type") == "PodScheduled" and cond.get("status") == "False":
            classified = _classify_scheduling_message(cond.get("message"))
            if classified is not None:
                return classified
            return str(cond.get("reason") or "Unschedulable")

    return "Pending timeout"


def extract_unschedulable_message(pod: Mapping[str, Any]) -> str | None:
    """The scheduler's message for a Pod it couldn't place, if any.

    That is the ``PodScheduled``/``False`` condition's message, e.g.
    ``0/3 nodes are available: 3 Insufficient cpu.``
    """
    for cond in (pod.get("status") or {}).get("conditions") or []:
        if cond.get("type") == "PodScheduled" and cond.get("status") == "False":
            message = cond.get("message")
            return str(message) if message else None
    return None


#: Storage-failure classifiers.
#:
#: Each entry is ``(needle, classification)``. Needles are substrings of the
#: kubelet/scheduler ``PodScheduled``/``False`` message; the first match wins.
#: Classifications are stable strings — operators may grep on them, so don't
#: rephrase casually.
_SCHEDULING_MESSAGE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("storageclass.storage.k8s.io", "StorageClass not found"),
    ("storage class", "StorageClass not found"),
    ("had volume node affinity conflict", "Volume zone mismatch"),
    ("node(s) had volume node affinity conflict", "Volume zone mismatch"),
    ("exceeded quota", "Quota exceeded"),
    ("forbidden: exceeded quota", "Quota exceeded"),
    ("pod has unbound immediate PersistentVolumeClaims", "PVC unbound"),
    ("unbound persistentvolumeclaim", "PVC unbound"),
    ("insufficient cpu", "Insufficient CPU"),
    ("insufficient memory", "Insufficient memory"),
    ("untolerated taint", "Untolerated taint"),
)


def _classify_scheduling_message(message: object) -> str | None:
    """Map a scheduler/kubelet failure message to a stable classification.

    Returns ``None`` when no known pattern matches, signalling the caller
    should fall back to the raw ``reason``.
    """
    if not isinstance(message, str) or not message:
        return None
    lowered = message.lower()
    for needle, classification in _SCHEDULING_MESSAGE_PATTERNS:
        if needle in lowered:
            return classification
    return None


def _iter_container_statuses(
    pod_status: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Yield every container status on a Pod, init + regular, in order.

    Handles both camelCase and snake_case keys because the kubernetes
    Python client serialises differently depending on whether the dict
    came from `to_dict()` or a raw watch event.
    """
    init_statuses = (
        pod_status.get("initContainerStatuses")
        or pod_status.get("init_container_statuses")
        or []
    )
    container_statuses = (
        pod_status.get("containerStatuses")
        or pod_status.get("container_statuses")
        or []
    )
    return [*init_statuses, *container_statuses]


def _collect_container_reasons(pod_status: Mapping[str, Any]) -> set[str]:
    """Gather non-empty terminated reasons across all containers."""
    reasons: set[str] = set()
    for cs in _iter_container_statuses(pod_status):
        terminated = (cs.get("state") or {}).get("terminated") or {}
        reason = terminated.get("reason")
        if reason:
            reasons.add(reason)
    return reasons
