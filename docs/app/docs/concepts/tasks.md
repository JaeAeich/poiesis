---
description: How a TES task becomes one Kubernetes Pod - the containers in a TaskPod, executor order, ignore_error, task logs and cancelling.
---

# Tasks and TaskPods

Every task runs as one Pod, the **TaskPod**, wrapped in a Kubernetes
`Job`. Init containers do the work in order; a sidecar records what
happens.

<TaskFigure />

- `tif` stages inputs, the executors run one after another, `tof`
  uploads outputs. All share the task's [volume](./task-volumes.md).
- An executor that exits non-zero stops the task, unless it sets
  [`ignore_error`](#executors-that-may-fail).
- `trec` writes state and logs to Postgres as the Pod runs; `tctl`
  steps in only when the Pod can't report for itself.

## The containers

| Container | Kind | Does |
| --- | --- | --- |
| `trec` | Native sidecar | Watches its own Pod and writes state and executor logs to Postgres. |
| `tif` | Init | Stages `inputs` onto the volume: `s3://`, `http(s)://`, `file://`, inline `content`. |
| `exec-0` … `exec-N` | Init | Your executors, in order, in your images. |
| `tof` | Init | Uploads `outputs` from the volume: `s3://`, `http(s)://`, `file://`. |
| `ack` | Main | Exits 0 so the Pod reaches `Succeeded`. Reuses the Poiesis image, so no second image pull. |

`trec` is a native sidecar: an init container with
`restartPolicy: Always`, a Kubernetes 1.29 feature. It starts before the
other init containers and stays up for the whole Pod. On `SIGTERM` it
reads the Pod once more, so the final state lands even if the watch
hasn't delivered the `Succeeded` event yet.

<PoiDiagram name="taskpod" />

## Executors

Executors run strictly in order, as init containers named `exec-{N}`.
If executor *i* fails, executors *i+1…n* never start and the task ends
in `EXECUTOR_ERROR`. Data passes between executors only through the
paths the task declares; see [Task paths](./task-volumes.md#task-paths).

Executors run with no shell, exactly as submitted: image, command,
working directory and environment come from the task.

<Callout type="info">

The Pod doesn't mount its ServiceAccount token. Only `trec` mounts one,
at `/var/run/secrets/kubernetes.io/serviceaccount`, so executors, which
run user images, can't call the Kubernetes API.

</Callout>

## Executors that may fail

By default the first executor that exits non-zero stops the task. An
executor with `"ignore_error": true` doesn't: its exit code is recorded
in the task logs and the next executor runs. If the rest succeed, the
task ends in `COMPLETE`.

```json
"executors": [
  {
    "image": "alpine:3.20",
    "command": ["sh", "-c", "exit 3"],
    "ignore_error": true
  },
  {"image": "alpine:3.20", "command": ["echo", "hello"]}
]
```

This task ends in `COMPLETE`, and `logs[0].logs[0].exit_code` is `3`.

Kubernetes stops the Pod when an init container fails, so Poiesis runs an
`ignore_error` executor under `/bin/sh`:

- The shell runs the command as submitted, as positional arguments, so
  nothing is re-quoted or expanded. It writes the exit code to the
  container's termination message (`/dev/termination-log`) and exits 0.
- The image must have `/bin/sh`. Without it the container can't start
  and the task ends in `EXECUTOR_ERROR`; its system log says the executor
  sets `ignore_error` and needs `/bin/sh`.
- `kubectl get pod` shows the container exited 0. The real exit code is
  in its `state.terminated.message`, where TRec and TCtl read it, and in
  the task logs.

## Task logs

`GET /tasks/{id}?view=FULL` returns one entry per finished executor in
`logs[].logs[]`, with its start and end time, exit code and output:

- `stdout` holds the last 64 KiB of the executor's container log. The
  log mixes the executor's stdout and stderr, so both end up here.
- `stderr` stays empty. Poiesis doesn't write the executor's output to
  its `stdout` and `stderr` paths (some engines rely on that, see
  [Sprocket](../guides/workflow-engines.md#sprocket)).
- If the log can't be read (for example, the ServiceAccount lacks
  `pods/log: get`), `stdout` stays empty and TRec or TCtl logs a
  warning. The task itself is unaffected.

The `BASIC` view leaves `stdout` and `stderr` out; `MINIMAL` has no logs.
`system_logs` holds lines from Poiesis itself, such as a non-zero exit of
`tif` or `tof`.

## Who records what

<FlowDiagram :spec="{
  title: 'Who writes a task state',
  h: 200,
  nodes: {
    api: { x: 4, y: 20, w: 118, label: 'API', sub: 'QUEUED, CANCELING' },
    trec: { x: 151, y: 20, w: 118, label: 'trec', sub: 'in the Pod' },
    db: { x: 298, y: 78, w: 118, label: 'Postgres', sub: 'write once' },
    tctl: { x: 151, y: 136, w: 118, label: 'tctl', sub: 'backstop' }
  },
  edges: [['api','db'],['trec','db'],['tctl','db']],
  hops: [
    { f: 'api', t: 'db', label: 'QUEUED', cap: 'CreateTask stores the task as QUEUED, then submits a Job and a volume owned by it.' },
    { f: 'trec', t: 'db', label: 'RUNNING', cap: 'trec writes RUNNING when the first executor starts, and executor logs as each one ends.' },
    { f: 'trec', t: 'db', label: 'COMPLETE', tone: 'ok', cap: 'On a clean run trec writes the final state itself.' },
    { f: 'tctl', t: 'db', label: 'SYSTEM_ERROR', tone: 'bad', cap: 'tctl writes it when the Pod could not: OOMKill, eviction, node loss, a Pod pending for over 5 minutes.' }
  ]
}" />

State changes go through one conditional `UPDATE` that requires the row
to be non-terminal and gives `CANCELING` precedence, so whichever of TRec
and TCtl writes first wins, without application locks. See
[Architecture](./architecture.md#tctl) for what TCtl reconciles.

## Cancelling

`POST /tasks/{id}:cancel` writes `CANCELING` and deletes the Job. The Pod
disappears before reaching a terminal phase; TCtl sees the deletion and
writes the final state, which lands as `CANCELED` because `CANCELING`
takes precedence.

## Tags

TES tag values are strings. Poiesis drops tags whose value is `null` and
accepts the task, as if the tag was never sent (in tag filters, sharing
scopes and what a decision service sees, too). Cromwell sends such a tag,
`parent_workflow_id`, for top-level workflows. Any other non-string value
(a number, an object) gets `422`.

## Read-only fields

Poiesis assigns task IDs, state, creation time and logs itself and
ignores client-supplied values (the TES API marks them read-only).
