"""What tctl does about one task, decided from plain data.

`decide` takes what one reconcile pass knows about a task (its DB view, its
Job, its Pods, the time and the timeouts) and returns the actions tctl
applies: write a terminal state, delete the Job, or nothing. It reads no
clock and calls neither Kubernetes nor the database; `core/tctl.py` gathers
the inputs and applies the actions.

The order of the checks, for a task:

    1. `CANCELING` with a Job not being deleted → delete the Job. A task
    the pass didn't read as non-terminal (already terminal, or unknown)
    gets nothing more.
    2. With Pods, each Pod in turn: the Job past its time limit, else a
    finished Pod, else a Pending Pod past its pending or unschedulable
    timeout. Nothing more is checked.
    3. Without a Pod, the Job: being deleted or complete stands for nothing
    (go on to 4); past its time limit or failed ends the task; otherwise it
    is alive and the task waits, unless the unschedulable timeout ran out.
    4. Non-terminal in the DB, seen by tctl for the orphan grace → orphan.

A terminal write that doesn't come from a finished Pod or Job (pending or
unschedulable timeout, orphan) is followed by `DeleteJob(retry=False)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from poiesis.api.tes.models import TesState
from poiesis.core import executor_shell
from poiesis.core.pod_status import (
    created_at,
    extract_job_failure,
    extract_pending_failure_reason,
    extract_terminal_reason,
    extract_unschedulable_message,
    filer_failure_log,
    is_lifecycle_stop,
    job_deadline_terminal,
    pod_terminated_terminal,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class TaskView:
    """A task as one pass sees it.

    Attributes:
        task_id: The task's id.
        canceling: The task was `CANCELING` when the pass read the DB.
        seen_for: Seconds tctl has seen the task non-terminal, by its own
            monotonic clock, this leadership term; None if the pass didn't
            read it as non-terminal (terminal, unknown, or only in the
            `CANCELING` read).
    """

    task_id: str
    canceling: bool = False
    seen_for: float | None = None


@dataclass(frozen=True)
class Timeouts:
    """The limits a pass applies, in seconds.

    Attributes:
        pending: How long a Pod bound to a node may stay Pending.
        unschedulable: How long a task may wait for its Pod to be created
            and scheduled; None waits until the Job's time limit.
        orphan_grace: How long tctl must have seen a task without a live
            Job or Pod before calling it an orphan.
    """

    pending: float
    unschedulable: float | None
    orphan_grace: float


@dataclass(frozen=True)
class WriteTerminal:
    """Propose a terminal state to `state.write_terminal_state`.

    Attributes:
        state: The proposed terminal state.
        reason: The reason stored with it.
        system_logs: The system log lines appended if the write lands
            (replaced by "task cancelled by client" when it lands as
            CANCELED).
        source: Which check proposed it, for tctl's log line.
        backfill_from_pod: The Pod whose executor logs are backfilled if
            the write lands; None when the write doesn't come from a Pod.
    """

    state: TesState
    reason: str | None
    system_logs: tuple[str, ...]
    source: str
    backfill_from_pod: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class DeleteJob:
    """Delete the task's Job.

    Attributes:
        retry: True for a `CANCELING` task: deleted on every pass while the
            Job is listed and not being deleted. False after a terminal
            write: deleted only if the `WriteTerminal` before it finalised
            the task, and not tried again.
    """

    retry: bool


Action = WriteTerminal | DeleteJob


def decide(
    task: TaskView,
    job: Mapping[str, Any] | None,
    pods: Sequence[Mapping[str, Any]],
    now: datetime,
    timeouts: Timeouts,
) -> list[Action]:
    """The actions for one task, in the order tctl applies them.

    Args:
        task: The task as the pass read it from the DB.
        job: The task's Job, if listed.
        pods: The task's Pods, in list order (usually zero or one).
        now: The wall-clock time Pod and Job ages are measured against.
        timeouts: The pass's limits.
    """
    actions: list[Action] = []
    if task.canceling and job is not None and not being_deleted(job):
        actions.append(DeleteJob(retry=True))
    if not task.canceling and task.seen_for is None:
        # Terminal in the DB, or not a task of this installation: its
        # finished Pod would only make a no-op write on every pass until
        # the Job's TTL removes it.
        return actions

    if pods:
        for pod in pods:
            actions.extend(_decide_pod(job, pod, now, timeouts))
        return actions

    if job is not None:
        accounted, job_actions = _decide_podless_job(job, now, timeouts)
        actions.extend(job_actions)
        if accounted:
            return actions

    if task.seen_for is not None and task.seen_for >= timeouts.orphan_grace:
        actions.append(
            WriteTerminal(
                state=TesState.SYSTEM_ERROR,
                reason="Pod disappeared before reaching terminal phase",
                system_logs=("pod disappeared before reaching terminal phase",),
                source="orphan",
            )
        )
        actions.append(DeleteJob(retry=False))
    return actions


def _decide_pod(
    job: Mapping[str, Any] | None,
    pod: Mapping[str, Any],
    now: datetime,
    timeouts: Timeouts,
) -> list[Action]:
    """Terminal state for one Pod, when its phase warrants it.

    The Job is read first: when its time limit ran out, the Job controller
    kills the Pod, whose containers then show only a signal's exit code
    (137, 143). The task ends with the time limit as its cause instead.
    """
    phase = ((pod.get("status") or {}).get("phase") or "").lower()

    deadline = job_deadline_terminal(job) if job is not None else None
    if deadline is not None:
        proposed, reason, line = deadline
        return [WriteTerminal(proposed, reason, (line,), "job-deadline", pod)]

    if phase in {"succeeded", "failed"}:
        proposed, reason = pod_terminated_terminal(extract_terminal_reason(pod))
        system_logs = tuple(terminal_system_logs(pod, proposed))
        return [WriteTerminal(proposed, reason, system_logs, "pod-terminal", pod)]

    timeout = (
        pending_timeout(pod, now, timeouts.pending, timeouts.unschedulable)
        if phase == "pending"
        else None
    )
    if timeout is None:
        return []
    pending_reason = extract_pending_failure_reason(pod)
    actions: list[Action] = [
        WriteTerminal(
            TesState.SYSTEM_ERROR,
            pending_reason,
            tuple(pending_system_logs(pod, timeout, pending_reason)),
            timeout.replace(" ", "-"),
            pod,
        )
    ]
    if (pod.get("metadata") or {}).get("namespace"):
        actions.append(DeleteJob(retry=False))
    return actions


def _decide_podless_job(
    job: Mapping[str, Any], now: datetime, timeouts: Timeouts
) -> tuple[bool, list[Action]]:
    """Actions for a task Job without a Pod, and whether it accounts for the task.

    A Job that is being deleted or has completed stands for nothing any
    more: False leaves its task to the orphan check. A failed Job (its
    time limit ran out and the Job controller removed the Pod) ends the
    task with its own reason. Any other Job is alive, and its task waits
    for a Pod: a ResourceQuota or an admission webhook may hold the Pod
    back until capacity frees up. Only the unschedulable timeout, when
    set, ends that wait.
    """
    if being_deleted(job):
        return False, []

    deadline = job_deadline_terminal(job)
    if deadline is not None:
        proposed, reason, line = deadline
        return True, [WriteTerminal(proposed, reason, (line,), "job-deadline")]

    finished, failure = extract_job_failure(job)
    if failure is not None:
        return True, [
            WriteTerminal(
                TesState.SYSTEM_ERROR,
                f"Job failed: {failure}",
                (f"job failed without a pod: {failure}",),
                "job-failed",
            )
        ]
    if finished:
        return False, []

    created = created_at(job)
    if (
        timeouts.unschedulable is not None
        and created is not None
        and (now - created).total_seconds() > timeouts.unschedulable
    ):
        return True, [
            WriteTerminal(
                TesState.SYSTEM_ERROR,
                "Job created no Pod",
                (
                    "unschedulable timeout: the Job created no Pod "
                    "(see the Job's events: quota, admission)",
                ),
                "job-no-pod",
            ),
            DeleteJob(retry=False),
        ]
    return True, []


def being_deleted(obj: Mapping[str, Any]) -> bool:
    """True iff the object carries a `deletionTimestamp`."""
    metadata = obj.get("metadata") or {}
    return bool(metadata.get("deletion_timestamp") or metadata.get("deletionTimestamp"))


def terminal_system_logs(
    pod: Mapping[str, Any],
    proposed: TesState,
) -> list[str]:
    """Emit human-readable diagnostics for non-COMPLETE terminal writes.

    Walks every container status and surfaces termination reasons that
    operators care about: OOMKill, non-zero exit, specific waiting
    reasons. trec and `ack` stopped as the Pod ends are left out
    (`is_lifecycle_stop`). Returns an empty list for COMPLETE (happy path
    needs no system_logs noise).
    """
    if proposed is TesState.COMPLETE:
        return []

    lines: list[str] = []
    wrapped = executor_shell.wrapped_executors(pod)
    status = pod.get("status") or {}
    for key in (
        "init_container_statuses",
        "initContainerStatuses",
        "container_statuses",
        "containerStatuses",
    ):
        for entry in status.get(key) or []:
            name = entry.get("name") or "?"
            terminated = (entry.get("state") or {}).get("terminated")
            if not terminated or is_lifecycle_stop(status, name, terminated):
                continue
            reason = terminated.get("reason")
            exit_code = terminated.get("exit_code") or terminated.get("exitCode")
            shell_failure = (
                executor_shell.start_failure_log(name, terminated, wrapped[name])
                if name in wrapped
                else None
            )
            filer_failure = filer_failure_log(name, terminated)
            if reason == "OOMKilled":
                lines.append(f"container {name} OOMKilled")
            elif shell_failure is not None:
                lines.append(shell_failure)
            elif filer_failure is not None:
                lines.append(filer_failure)
            elif exit_code not in (None, 0):
                lines.append(f"container {name} exited with code {exit_code}")
    if not lines:
        lines.append(f"task ended in {proposed.value}")
    return lines


def pending_system_logs(pod: Mapping[str, Any], timeout: str, reason: str) -> list[str]:
    """The system_logs of a timeout in Pending: the reason, then the scheduler's.

    `timeout` names which timeout ran out (`pending_timeout`); `reason` is
    a stable classification. The scheduler's own message says which nodes
    it tried and why none fits, so it is kept as a second line.
    """
    lines = [f"{timeout}: {reason}"]
    message = extract_unschedulable_message(pod)
    if message:
        lines.append(f"scheduler: {message}")
    return lines


def parse_kubelet_ts(value: Any) -> datetime | None:
    """Best-effort parse of a kubelet ISO-8601 timestamp."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def pending_timeout(
    pod: Mapping[str, Any],
    now: datetime,
    pending_seconds: float,
    unschedulable_seconds: float | None,
) -> str | None:
    """Which timeout a Pending `pod` has run out of, if any.

    A Pod bound to a node has a `status.startTime`; after `pending_seconds`
    from it, "pending timeout". A Pod the scheduler hasn't placed (no node
    with room, unbindable PVC, taints) has none: on a busy cluster that is
    queueing, not a fault. It is timed from `metadata.creationTimestamp`
    against `unschedulable_seconds`, and never when that is None:
    "unschedulable timeout".
    """
    status = pod.get("status") or {}
    started = parse_kubelet_ts(status.get("startTime") or status.get("start_time"))
    if started is not None:
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if (now - started).total_seconds() > pending_seconds:
            return "pending timeout"
        return None
    if unschedulable_seconds is None:
        return None
    created = created_at(pod)
    if created is not None and (now - created).total_seconds() > unschedulable_seconds:
        return "unschedulable timeout"
    return None
