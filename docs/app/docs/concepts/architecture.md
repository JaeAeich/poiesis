---
description: The API, TaskPods, TRec, TCtl and Postgres - who writes what, and why the state machine is race-correct without locks.
---

# Architecture

Every TES task runs as a single Kubernetes Pod, wrapped in a Job, with
state in PostgreSQL. The API never schedules or reconciles anything; it
writes rows and creates Jobs.

<PoiDiagram name="overview" />

## Lifecycle

<PoiDiagram name="lifecycle" />

## API

FastAPI under `/ga4gh/tes/v1` (see [TES API](../reference/api.md)).

- `CreateTask` writes `QUEUED`, submits a Job, and creates a PVC owned
  by the Job.
- `CancelTask` writes `CANCELING` and deletes the Job; the
  conditional-update writer guarantees the final state lands as
  `CANCELED`. Cancelling a task that is already `CANCELING` deletes the
  Job again, so a cancel whose delete failed can be retried.

## TaskPod

Init containers run strictly in order. `trec` starts before them and
stays alive for the whole Pod. Every container but `ack` mounts the task
volume at `/transfer`. See [Tasks and TaskPods](./tasks.md).

## TRec

The in-pod recorder. It watches its own Pod and writes:

- `INITIALIZING` when it starts, before `tif` and the executors;
- `RUNNING` when it sees the first executor start (or end, if the watch
  missed the start);
- one `executor_logs` row per executor: start, end, exit code, and the
  last 64 KiB of the container log as `stdout` (or of the executor's
  `stdout` and `stderr` files, read from the task volume);
- `system_logs` lines when `tif` or `tof` exit non-zero.

It never writes the terminal state; TCtl does. It exits when the Pod
reaches a terminal phase or on `SIGTERM`, which the kubelet sends once
the other containers have ended: it reads the Pod once more, records what
the watch hadn't delivered, and exits 0, so the Pod ends without waiting
out its grace period.

## TCtl

The only writer of terminal state, leader-elected
(`coordination.k8s.io` Leases): one replica is active at a time, so more
replicas give faster failover, not throughput. The Lease is kept in the
release namespace, also when `taskpods.namespace` puts the tasks
elsewhere; if a Lease call fails, TCtl logs it and tries again 10
seconds later without reconciling. Every 5 seconds the
leader reads the non-terminal tasks from Postgres, then lists the Jobs
and Pods labelled `poiesis.io/task`. It has seven jobs:

- **Phase reconciliation**: a `Succeeded` Pod becomes `COMPLETE`; a
  `Failed` one `SYSTEM_ERROR` (OOMKill, eviction, node loss, a failed
  `tif` or `tof`) or `EXECUTOR_ERROR` (any other failure, and a declared
  output the executors didn't produce). A failed filer's cause, read
  from its termination message, goes to `system_logs`; see
  [Staging failures](./storage.md#staging-failures). Executors TRec
  didn't record get their `executor_logs` rows here, output included.
- **Time limit**: when the Job's `Failed` (or `FailureTarget`) condition
  says `DeadlineExceeded`, the task becomes `SYSTEM_ERROR` with reason
  `DeadlineExceeded` and "task exceeded its time limit of N seconds" in
  `system_logs`. TCtl reads the Job first, so this holds whether the Pod
  is gone, `Failed`, still stopping or never scheduled; the exit code of
  the killed executor (137, 143) is not taken as the cause.
- **Missing-pod reconciliation**: a non-terminal task that has neither
  a Job nor a Pod on every pass for 30 seconds becomes `SYSTEM_ERROR`
  ("Pod disappeared before reaching terminal phase"). TCtl times the 30
  seconds on its own clock, and a new leader starts them again. A task
  whose Job exists is not missing, whether or not the Job has a Pod yet.
  Cancelled tasks delete the Job, so their Pod vanishes too; `CANCELING`
  takes precedence, so they land as `CANCELED`.
- **Jobs without a Pod**: a failed Job whose Pod is gone (the Pod was
  deleted or lost with its node) becomes `SYSTEM_ERROR` with the Job's
  reason, such as `Job failed: BackoffLimitExceeded`. A live Job that
  has created no Pod yet (a ResourceQuota is full, an admission webhook
  rejects the Pod) keeps its task `QUEUED`: see below.
- **Pending timeout**: a Pod bound to a node but still `Pending` 5
  minutes after `status.startTime` becomes `SYSTEM_ERROR`, with the
  reason in `system_logs` (an image that can't be pulled, a volume that
  can't be mounted). This timeout isn't configurable.
- **Waiting to be scheduled**: a Pod the scheduler hasn't placed (no
  node with room, an unbindable PVC, taints) has no `startTime`. On a
  busy cluster that is queueing, not a fault: by default the task stays
  `QUEUED` until the Job's [time limit](./tasks.md#time-limit) ends it.
  Set `tctl.unschedulableTimeoutSeconds` to fail fast: a task waiting
  longer than that, counted from the Pod's creation (or the Job's, with
  no Pod yet), becomes `SYSTEM_ERROR` with the scheduler's message, or
  `Job created no Pod`, in `system_logs`.

- **Job cleanup**: TCtl deletes the Job of every `CANCELING` task that
  still has one, on each pass until it is gone. It also deletes the Job
  after it ends a task for a missing Pod or a pending or unschedulable
  timeout, so a Pod that becomes runnable later can't run a task
  already reported as failed. If that delete fails, TCtl logs it and
  doesn't retry; the Job's [time limit](./tasks.md#time-limit), if
  set, still ends it. The Job of a finished Pod is left to its TTL.
  Deleting Jobs is TCtl's only write to Kubernetes.

TCtl is on every path: TRec never finalises a task, clean runs included.

## Postgres

| Table | Holds |
| --- | --- |
| `tasks` | The canonical task row, with `owner` and `groups`. |
| `task_inputs`, `task_outputs`, `task_executors` | Typed children: a relational TES schema. |
| `task_logs` | One row per attempt: `system_logs[]`, metadata, timestamps, and the [files `tof` uploaded](./storage.md#output-file-logs) (`outputs`). |
| `executor_logs` | One row per executor exit: start, end, exit code, output tail. |
| `api_keys` | [API keys](./api-keys.md): SHA-256 hashes and metadata, never keys. |

Terminal states go through `write_terminal_state`, a conditional
`UPDATE` that requires the row to be non-terminal and gives `CANCELING`
precedence. TRec's `INITIALIZING` update applies only to a `QUEUED` row, its
`RUNNING` update only to a `QUEUED` or `INITIALIZING` one, so neither
overwrites `CANCELING` or a final state. That
keeps TCtl's write and a racing cancel write-once without application
locks.

Migrations live under `./migrations/` and are applied by
[golang-migrate](https://github.com/golang-migrate/migrate): a Helm hook
in the chart, a Job in the dev manifest.

## Requirements

- **Kubernetes 1.29+**, for native sidecar containers. The chart pins
  `kubeVersion: ">=1.29.0-0"`, so installs fail fast elsewhere.
- **PostgreSQL**, shared by the API, TRec and TCtl. Managed Postgres or
  an HA operator in production.
- **A default StorageClass** with `ReadWriteOnce` volumes (or set
  `taskpods.persistence.storageClass`).
- **Object storage** reachable from the task namespace, for inputs and
  outputs.

## Trust boundary

| Surface | Enforcement |
| --- | --- |
| HTTP handlers | Every TES and API key route requires a principal. `service-info` and the resource metadata are public. |
| Database | `tasks.owner` is stamped on every insert; reads are scoped by [authorization](./authorization.md). |
| Workers | TRec and TCtl access the database directly, without an owner filter. |

Workers act as the system, not on behalf of a user. They are inside the
trust boundary; the API is where authorization applies.
