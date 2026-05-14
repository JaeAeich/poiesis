# Glossary

## Poiesis components

### TaskPod

The single Kubernetes Pod that runs an entire TES [task](#task)
end-to-end. Wrapped in a [Job](#kubernetes-job). Composed of init
containers ([TIF](#task-input-filer-tif),
[executors](#executor), [TOF](#task-output-filer-tof),
[Ack](#ack)) plus a [TRec](#task-recorder-trec) native sidecar that
records state to PostgreSQL.

### Task Input Filer (TIF)

Init container that stages `TesTask.inputs` onto the shared
[Task PVC](#task-pvc). Supports `s3://`, `http(s)://`, `file://`, and
inline `content`.

### Task Output Filer (TOF)

Init container that uploads `TesTask.outputs` from the PVC after the
last executor finishes. Supports `s3://` and `file://`.

### Executor

One step in a task's sequenced execution. Runs as an init container
named `exec-{N}`. Failure of executor _i_ aborts executors _i+1..n_.

### Ack

Regular main container that exits 0 so the Pod reaches `Succeeded`.
Reuses the Poiesis image — no second image pull.

### Task Recorder (TRec)

Native sidecar (K8s 1.29+: init container with `restartPolicy: Always`)
that watches its own Pod and writes state to Postgres. On SIGTERM it
does a final pod read so terminal state lands even when the watch hasn't
yet delivered the `Succeeded` event.

### Task Controller (TCtl)

Leader-elected `Deployment` (default 3 replicas, `coordination.k8s.io`
Leases). Backstop reconciler: writes terminal state for failures TRec
cannot self-report — OOMKill before TRec started, eviction, node loss,
PVC bind failure, `activeDeadlineSeconds` exceeded, pending timeout.

### Task PVC

`PersistentVolumeClaim` sized to `TesResources.disk_gb`, mounted at
`/transfer` in every TaskPod container. Owned by the wrapping
[Job](#kubernetes-job); kube-controller-manager GC handles cleanup.

## General

### Task Execution Service (TES)

[GA4GH](https://www.ga4gh.org/) standard for a RESTful task-submission
API. Poiesis implements TES `v1.1.0`.
[Spec](https://github.com/ga4gh/task-execution-schemas).

### Task

A single unit of computational work: inputs, sequenced
[executors](#executor), outputs, resources. Terminal states:
`COMPLETE`, `EXECUTOR_ERROR`, `SYSTEM_ERROR`, `CANCELED`.

### Kubernetes (K8s)

Container orchestration platform. Poiesis requires **1.29+** for native
sidecar containers.

### Kubernetes Job

Controller that runs one or more [Pods](#kubernetes-pod) to completion.
Poiesis wraps each TaskPod in a Job for `ttlSecondsAfterFinished`
cleanup.

### Kubernetes Pod

Smallest deployable unit. One or more containers sharing network and
storage. The TaskPod is a Pod composed of init containers plus a
native sidecar.

### Kubernetes Persistent Volume Claim (PVC)

A request for storage, fulfilled by a `PersistentVolume`. One per
task — see [Task PVC](#task-pvc).
