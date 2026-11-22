"""tctl's Prometheus metrics.

Updated by the control loop in `poiesis.core.tctl` and served on their own
port by `poiesis.core.metrics.serve`. The task gauges are set by the leader
only, from one grouped query at most every `TASK_GAUGE_INTERVAL_SECONDS`;
a standby clears them, so a sum over the tctl replicas counts each task once.

Every label has a bounded set of values: TES states, the reconciler's check
names (`WriteTerminal.source`) and Kubernetes operation names.
"""

from __future__ import annotations

from enum import StrEnum

from prometheus_client import Counter, Gauge, Histogram

from poiesis.db.state import NON_TERMINAL_STATES
from poiesis.tes.models import TesState

#: Seconds between two refreshes of the task gauges.
TASK_GAUGE_INTERVAL_SECONDS = 30

#: The checks that propose a terminal state (`WriteTerminal.source`); any
#: other source is counted as ``other``.
TRANSITION_REASONS = frozenset(
    {
        "pod-terminal",
        "job-deadline",
        "job-failed",
        "job-complete",
        "pending-timeout",
        "unschedulable-timeout",
        "terminating-timeout",
        "orphan",
    }
)


class K8sOperation(StrEnum):
    """The Kubernetes calls tctl counts errors of."""

    LEASE = "lease"
    LIST_JOBS = "list_jobs"
    LIST_PODS = "list_pods"
    LIST_EVENTS = "list_events"
    DELETE_JOB = "delete_job"


IS_LEADER = Gauge(
    "poiesis_tctl_is_leader", "1 while this tctl instance holds the leader Lease."
)
RECONCILE_DURATION = Histogram(
    "poiesis_tctl_reconcile_duration_seconds",
    "Time one reconcile pass took.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
RECONCILE_LAST_SUCCESS = Gauge(
    "poiesis_tctl_reconcile_last_success_timestamp_seconds",
    "Unix time the last reconcile pass ended without an error.",
)
RECONCILE_ERRORS = Counter(
    "poiesis_tctl_reconcile_errors", "Reconcile passes that raised."
)
TASKS = Gauge(
    "poiesis_tasks",
    "Tasks in the database, by TES state (leader only).",
    ["state"],
)
OLDEST_TASK_AGE = Gauge(
    "poiesis_tasks_oldest_age_seconds",
    "Age of the oldest task in each non-terminal state (leader only).",
    ["state"],
)
TERMINAL_TRANSITIONS = Counter(
    "poiesis_tctl_terminal_transitions",
    "Terminal states tctl wrote, by state and the check that proposed it.",
    ["state", "reason"],
)
K8S_ERRORS = Counter(
    "poiesis_tctl_kubernetes_errors",
    "Kubernetes API calls of tctl that failed, by operation.",
    ["operation"],
)
for _operation in K8sOperation:
    K8S_ERRORS.labels(operation=_operation.value)
LEASE_RENEW_FAILURES = Counter(
    "poiesis_tctl_lease_renew_failures",
    "Renewals of the leader Lease that failed, ending this instance's term.",
)


def count_transition(state: TesState, source: str) -> None:
    """Count one terminal write of ``state`` proposed by the check ``source``."""
    reason = source if source in TRANSITION_REASONS else "other"
    TERMINAL_TRANSITIONS.labels(state=state.value, reason=reason).inc()


def count_k8s_error(operation: K8sOperation) -> None:
    """Count one failed Kubernetes call of ``operation``."""
    K8S_ERRORS.labels(operation=operation.value).inc()


def set_task_gauges(counts: dict[str, tuple[int, float | None]]) -> None:
    """Set the task gauges from ``{state: (count, oldest age in seconds)}``.

    Every TES state gets a count, 0 when absent; every non-terminal state
    gets an oldest age, 0 when it has no task.
    """
    for state in TesState:
        count, oldest = counts.get(state.value, (0, None))
        TASKS.labels(state=state.value).set(count)
        if state.value in NON_TERMINAL_STATES:
            OLDEST_TASK_AGE.labels(state=state.value).set(oldest or 0)


def clear_task_gauges() -> None:
    """Drop the task gauges: a standby doesn't report them."""
    TASKS.clear()
    OLDEST_TASK_AGE.clear()
