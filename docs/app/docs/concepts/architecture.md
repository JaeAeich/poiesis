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
  `CANCELED`.

## TaskPod

Init containers run strictly in order. `trec` starts before them and
stays alive for the whole Pod. Every container but `ack` mounts the task
volume at `/transfer`. See [Tasks and TaskPods](./tasks.md).

## TRec

The in-pod recorder. It watches its own Pod and writes:

- `RUNNING` when it starts, before `tif` and the executors;
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
replicas give faster failover, not throughput. Every 5 seconds the
leader lists the Pods labelled `poiesis.io/task` and the non-terminal
tasks in Postgres. It has three jobs:

- **Phase reconciliation**: a `Succeeded` Pod becomes `COMPLETE`; a
  `Failed` one `SYSTEM_ERROR` (OOMKill, eviction, node loss, deadline)
  or `EXECUTOR_ERROR` (any other failure). Executors TRec didn't record
  get their `executor_logs` rows here, output included.
- **Missing-pod reconciliation**: a non-terminal task older than 30
  seconds with no Pod becomes `SYSTEM_ERROR`. Cancelled tasks delete the
  Job, so their Pod vanishes too; `CANCELING` takes precedence, so they
  land as `CANCELED`.
- **Pending timeout**: a Pod still `Pending` with a `status.startTime`
  older than 5 minutes becomes `SYSTEM_ERROR` (an image that can't be
  pulled). A Pod that is never scheduled (unbindable PVC, no fitting
  node) has no `startTime`; it ends when the Job's
  `activeDeadlineSeconds` runs out (`taskpods.activeDeadlineSeconds`,
  one hour by default; never, if that is `null`). See
  [Time limit](./tasks.md#time-limit).

TCtl is on every path: TRec never finalises a task, clean runs included.

## Postgres

| Table | Holds |
| --- | --- |
| `tasks` | The canonical task row, with `owner` and `groups`. |
| `task_inputs`, `task_outputs`, `task_executors` | Typed children: a relational TES schema. |
| `task_logs` | One row per attempt: `system_logs[]`, metadata, timestamps. |
| `executor_logs` | One row per executor exit: start, end, exit code, output tail. |
| `api_keys` | [API keys](./api-keys.md): SHA-256 hashes and metadata, never keys. |

Terminal states go through `write_terminal_state`, a conditional
`UPDATE` that requires the row to be non-terminal and gives `CANCELING`
precedence. TRec's `RUNNING` update applies only to a `QUEUED` row. That
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
