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
from enum import Enum
from typing import TYPE_CHECKING, Any

from poiesis.api.tes.models import TesState

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
    OOM_KILLED = "OOMKilled"
    EVICTED = "Evicted"
    NODE_LOST = "NodeLost"
    DEADLINE_EXCEEDED = "DeadlineExceeded"
    PVC_BIND_FAILURE = "PVCBindFailure"
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
    """Map a Pod-termination reason to a terminal TES state + reason string."""
    if pod_reason == PodTerminationReason.COMPLETED.value:
        return TesState.COMPLETE, None
    if pod_reason in {
        PodTerminationReason.OOM_KILLED.value,
        PodTerminationReason.EVICTED.value,
        PodTerminationReason.NODE_LOST.value,
        PodTerminationReason.DEADLINE_EXCEEDED.value,
        PodTerminationReason.PVC_BIND_FAILURE.value,
    }:
        return TesState.SYSTEM_ERROR, pod_reason
    return TesState.EXECUTOR_ERROR, pod_reason


def _collect_container_reasons(pod_status: Mapping[str, Any]) -> set[str]:
    """Gather non-empty terminated reasons across all containers."""
    reasons: set[str] = set()
    for field in (
        "initContainerStatuses",
        "init_container_statuses",
        "containerStatuses",
        "container_statuses",
    ):
        for cs in pod_status.get(field) or []:
            terminated = (cs.get("state") or {}).get("terminated") or {}
            reason = terminated.get("reason")
            if reason:
                reasons.add(reason)
    return reasons
