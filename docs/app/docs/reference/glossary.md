---
description: Poiesis and Kubernetes terms in one place - TaskPod, TIF, TOF, TRec, TCtl, executors, owners, issuers and more.
---

# Glossary

## Poiesis

### TaskPod

The single Kubernetes Pod that runs a whole TES [task](#task), wrapped in
a [Job](#kubernetes-job). Init containers ([TIF](#task-input-filer-tif),
[executors](#executor), [TOF](#task-output-filer-tof)), a main
[Ack](#ack) container, and a [TRec](#task-recorder-trec) native sidecar
that records progress to PostgreSQL. See [Tasks and TaskPods](../concepts/tasks.md).

### Task Input Filer (TIF)

Init container that stages `inputs` onto the [task volume](#task-volume).
Supports `s3://`, `http(s)://`, `file://` and inline `content`.

### Task Output Filer (TOF)

Init container that uploads `outputs` from the volume after the last
executor finishes. Supports `s3://`, `http(s)://` and `file://`.

### Executor

One step of a task. Runs as an init container named `exec-{N}`. A failure
of executor *i* stops executors *i+1…n*, unless executor *i* sets
[`ignore_error`](../concepts/tasks.md#executors-that-may-fail).

### Ack

Main container that exits 0 so the Pod reaches `Succeeded`. Reuses the
Poiesis image, so no second image pull.

### Task Recorder (TRec)

Native sidecar (an init container with `restartPolicy: Always`, K8s
1.29+) that watches its own Pod, marks the task `RUNNING` and writes
executor logs (and filer failures) to Postgres. It never writes the
terminal state; that is [TCtl](#task-controller-tctl)'s.

### Task Controller (TCtl)

Leader-elected Deployment (`coordination.k8s.io` Leases), the sole
writer of terminal task state: when the Pod succeeds or fails (an
OOMKill, eviction, `activeDeadlineSeconds` exceeded, …), when it stays
`Pending` for over 5 minutes (e.g. a volume that can't be bound), or
when a task's Pod is gone (node loss, a manual delete).

### Task volume

The `PersistentVolumeClaim` of a task, sized to `resources.disk_gb` and
mounted at `/transfer` in every TaskPod container, and at the task's
paths in executors. Owned by the task's [Job](#kubernetes-job), so the
garbage collector deletes it. See [Task volumes](../concepts/task-volumes.md).

### Owner

The opaque id stamped on every task and API key:
`<namespace>|<subject>`, by default the issuer and the token's `sub`.
Callers see their own tasks. See
[Owner and namespace](../concepts/authentication.md#owner-and-namespace).

### Issuer

An identity provider Poiesis trusts, listed in `auth.issuers`. A token's
`iss` picks its issuer by exact match. See
[Authentication](../concepts/authentication.md).

### API key

A `poi_…` credential minted by an owner with a token, for clients that
outlive a token, such as workflow engines. See
[API keys](../concepts/api-keys.md).

### Decision service

An external OpenID AuthZEN 1.0 endpoint that decides what a caller may
do, in the `tes-authzen/2` profile. See
[Authorization](../concepts/authorization.md#decision-service).

## General

### Task Execution Service (TES)

[GA4GH](https://www.ga4gh.org/) standard for a REST task-submission API.
Poiesis implements TES `v1.1.0`. See [TES in 5 minutes](../start/tes.md).

### Task

A single unit of work: inputs, ordered [executors](#executor), outputs,
resources. Terminal states: `COMPLETE`, `EXECUTOR_ERROR`, `SYSTEM_ERROR`,
`CANCELED`.

### Kubernetes (K8s)

Container orchestration platform. Poiesis needs **1.29+** for native
sidecar containers.

### Kubernetes Job

Controller that runs one or more [Pods](#kubernetes-pod) to completion.
Poiesis wraps each TaskPod in a Job for `ttlSecondsAfterFinished`
cleanup.

### Kubernetes Pod

The smallest deployable unit: one or more containers sharing network and
storage.

### PersistentVolumeClaim (PVC)

A request for storage, fulfilled by a `PersistentVolume`. One per task:
see [Task volume](#task-volume).
