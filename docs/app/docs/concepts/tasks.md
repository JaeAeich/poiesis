---
description: How a TES task becomes one Kubernetes Pod - the containers in a TaskPod, executor order, ignore_error, stdin/stdout/stderr files, task logs and cancelling.
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
- `trec` marks the task `RUNNING` and writes executor logs to Postgres
  as the Pod runs; `tctl` writes every final state.

## The containers

| Container | Kind | Does |
| --- | --- | --- |
| `trec` | Native sidecar | Watches its own Pod, marks the task `RUNNING` and writes executor logs to Postgres. |
| `tif` | Init | Stages `inputs` onto the volume: `s3://`, `http(s)://`, `file://`, inline `content`, then creates the task's [directories](./task-volumes.md#task-paths) that have no mount of their own. Only if the task has inputs or such directories. |
| `exec-0` … `exec-N` | Init | Your executors, in order, in your images. |
| `tof` | Init | Uploads `outputs` from the volume: `s3://`, `http(s)://`, `file://`. Only if the task has outputs. |
| `ack` | Main | Exits 0 so the Pod reaches `Succeeded`. Reuses the Poiesis image, so no second image pull. |

`trec` is a native sidecar: an init container with
`restartPolicy: Always`, a Kubernetes 1.29 feature. It starts before the
other init containers and stays up for the whole Pod. It never writes
the final state: TCtl does, and backfills any executor logs TRec missed.

<PoiDiagram name="taskpod" />

## Executors

Executors run strictly in order, as init containers named `exec-{N}`.
If executor *i* fails, executors *i+1…n* never start and the task ends
in `EXECUTOR_ERROR`. Data passes between executors only through the
paths the task declares; see [Task paths](./task-volumes.md#task-paths).

Executors run with no shell, exactly as submitted: image, command,
working directory and environment come from the task. Only an executor
that sets [`ignore_error`](#executors-that-may-fail) or
[`stdin`, `stdout` or `stderr`](#stdin-stdout-and-stderr) runs under
`/bin/sh`, which its image must then have.

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

## stdin, stdout and stderr

An executor's `stdin` is a file in its container to read standard input
from; `stdout` and `stderr` are files to write standard output and error
to. Kubernetes can't connect a container's streams to files, so an
executor that sets any of them runs under `/bin/sh`, which opens the
files and then `exec`s the command:

- The command is passed as positional arguments, so nothing is re-quoted
  or expanded, and `exec` keeps its PID, signals and exit code. With
  `ignore_error` too, one wrapper does both.
- The directory of `stdout` and `stderr` is created if missing. The same
  path for both gets both streams, in order.
- The paths must be absolute (`400` otherwise). Put them under a path
  the task declares (an input, output or volume) to keep the files: like
  anything else an executor writes, a file elsewhere is lost with its
  container.
- The image must have `/bin/sh`. Without it the container can't start
  and the task ends in `EXECUTOR_ERROR`; its system log says the executor
  sets `stdout` (or `stdin`, `stderr`), which needs `/bin/sh` in its
  image.
- The container's own stdin stays closed: `stdin` comes from the file
  only.

## Task logs

`GET /tasks/{id}?view=FULL` returns one entry per finished executor in
`logs[].logs[]`, with its start and end time, exit code and output:

- `stdout` holds the last 64 KiB of the executor's container log. The
  log mixes the executor's stdout and stderr, so both end up here, and
  `stderr` stays empty.
- An executor that writes its stdout or stderr to a
  [file](#stdin-stdout-and-stderr) on the task volume gets the last
  64 KiB of that file instead, as `stdout` or `stderr`; TRec reads it
  from the volume, without following symlinks. The container log then
  goes to the other field. A file elsewhere in the container can't be
  read, so that stream is missing from the task logs.
- If the log can't be read (for example, the ServiceAccount lacks
  `pods/log: get`), `stdout` stays empty and TRec or TCtl logs a
  warning. The task itself is unaffected. TCtl, which backfills logs
  TRec missed, has no access to task volumes and stores only the
  container log.

The `BASIC` view leaves `stdout`, `stderr` and `system_logs` out;
`MINIMAL` has no logs.
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
    tctl: { x: 151, y: 136, w: 118, label: 'tctl', sub: 'final states' }
  },
  edges: [['api','db'],['trec','db'],['tctl','db']],
  hops: [
    { f: 'api', t: 'db', label: 'QUEUED', cap: 'CreateTask stores the task as QUEUED, then submits a Job and a volume owned by it.' },
    { f: 'trec', t: 'db', label: 'RUNNING', cap: 'trec writes RUNNING when it starts, before inputs are staged, and executor logs as each one ends.' },
    { f: 'tctl', t: 'db', label: 'COMPLETE', tone: 'ok', cap: 'Polling every 5 s, tctl sees the Pod Succeeded and writes the final state. trec never does.' },
    { f: 'tctl', t: 'db', label: 'SYSTEM_ERROR', tone: 'bad', cap: 'Also from tctl: OOMKill, eviction, node loss, a started Pod still Pending after 5 minutes, a Pod that vanished.' }
  ]
}" />

Final states go through a conditional `UPDATE` that requires the row
to be non-terminal and gives `CANCELING` precedence, so a final state
lands once and a racing cancel wins, without application locks. See
[Architecture](./architecture.md#tctl) for what TCtl reconciles.

## Time limit

Each task's Job sets `activeDeadlineSeconds: 3600`, which the chart
doesn't expose. A task still running after an hour is stopped by
Kubernetes and fails.

## Cancelling

`POST /tasks/{id}:cancel` writes `CANCELING` and deletes the Job. The Pod
disappears before reaching a terminal phase; TCtl finds the task
without a Pod and writes the final state, which lands as `CANCELED` because `CANCELING`
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
