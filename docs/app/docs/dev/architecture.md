# Architecture

Every TES task runs as a single Kubernetes Pod, wrapped in a Job, with
state in PostgreSQL.

## Lifecycle

![Task lifecycle sequence](/diagrams/lifecycle.svg)

## TaskPod

<img src="/diagrams/taskpod.svg" alt="TaskPod container layout" style="max-width: 420px; display: block; margin: 1em auto;" />

Init containers run strictly sequentially. `trec` starts before them
and stays alive across the entire Pod lifecycle. All containers share
the Task PVC at `/transfer`.

## API

FastAPI under `/ga4gh/tes/v1`:

| Endpoint | Operation |
| --- | --- |
| `GET /service-info` | `GetServiceInfo` |
| `POST /tasks` | `CreateTask` |
| `GET /tasks` | `ListTasks` |
| `GET /tasks/{id}` | `GetTask` |
| `POST /tasks/{id}:cancel` | `CancelTask` |

`CreateTask` writes `QUEUED`, submits a Job, creates a PVC owned by
the Job. `CancelTask` writes `CANCELING` and deletes the Job; the
conditional-update writer guarantees the final state lands as
`CANCELED`.

## TRec

In-pod recorder. Watches its own Pod, writes:

- `RUNNING` on first executor start
- `executor_logs` rows per executor (start/end/exit code)
- `system_logs` lines on TIF/TOF non-zero exit
- Terminal state (`COMPLETE` / `EXECUTOR_ERROR` / `SYSTEM_ERROR`)

On `SIGTERM`, does a final pod read so terminal state lands even when
the watch hasn't delivered the `Succeeded` event yet.

## TCtl

Leader-elected backstop (3 replicas, `coordination.k8s.io` Leases).
Pod informer scoped to `poiesis.io/task`. Three responsibilities:

- **Phase reconciliation** — `Succeeded`/`Failed` → terminal state.
- **Deleted-pod reconciliation** — cancelled tasks delete the Job;
  the Pod vanishes before reaching a terminal phase. TCtl handles the
  `DELETED` event and writes terminal state (CANCELING-precedence
  rule makes this land as `CANCELED`).
- **Pending timeout** — `status.startTime` older than 5 minutes
  becomes `SYSTEM_ERROR` (bad image, unbindable PVC, no schedulable
  node).

TCtl is off the happy path. TRec handles clean runs.

## Postgres

| Table | Holds |
| --- | --- |
| `tasks` | Canonical task row |
| `task_inputs`, `task_outputs`, `task_executors` | Typed children, relational TES schema |
| `task_logs` | One row per attempt: `system_logs[]`, metadata, timestamps |
| `executor_logs` | One row per executor exit: start/end/exit code |

State transitions go through `write_terminal_state` — a conditional
UPDATE that requires the row to be non-terminal and gives `CANCELING`
precedence. This is what makes the TRec/TCtl race write-once without
application locks.
