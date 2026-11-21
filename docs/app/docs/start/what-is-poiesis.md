---
description: Poiesis is a GA4GH TES v1.1 server for Kubernetes. Every task runs as one Pod with its own volume.
---

# What is Poiesis

Poiesis is a [GA4GH Task Execution Service](./tes.md) (TES `v1.1.0`) for
Kubernetes. Workflow engines send it tasks over a REST API; it runs each
task as **one Pod with its own volume**. One container image (plus one
for migrations), one PostgreSQL schema, no broker.

<TaskFigure />

- Your image and command run as submitted. Nothing is wrapped or injected
  (except a `/bin/sh` wrapper for executors that set
  [`ignore_error`](../concepts/tasks.md#executors-that-may-fail)).
- Inputs are staged onto the task's volume, outputs are uploaded from it,
  and the volume is deleted with the task.
- Callers authenticate with tokens from your identity provider, or with
  [API keys](../concepts/api-keys.md) for long workflow runs.

<PoiDiagram name="overview" />

## Components

| Component | Role |
| --- | --- |
| **API** | FastAPI service exposing TES under `/ga4gh/tes/v1`. No scheduler, no reconciler. |
| **TaskPod** | One Pod per task: `trec` (sidecar), then `tif`, `exec-0..N`, `tof`, `ack`. `tif` and `tof` only if the task has inputs or outputs. |
| **TRec** | In-pod recorder. Watches the surrounding Pod, marks the task `INITIALIZING`, then `RUNNING` when the first executor starts, and writes executor logs. |
| **TCtl** | Leader-elected Deployment. Writes every final state from the Pod's phase, including OOMKill, eviction, node loss, pending timeouts and vanished Pods. |
| **Postgres** | Relational store. Conditional `UPDATE`s make concurrent state writes (TRec, TCtl, a cancel) race-correct. |

See [Tasks and TaskPods](../concepts/tasks.md) and
[Architecture](../concepts/architecture.md) for how they fit together.

## Storage protocols

Inputs: `s3://`, `http://`, `https://` and inline `content`.
Outputs: `s3://`, `http://` and `https://`. `file://` works for both when
the operator allows it, and so do `gs://` (Google Cloud Storage) and
`az://` (Azure Blob Storage), which are experimental. See
[Storage and staging](../concepts/storage.md).

## What's yours and what's ours

| You | Poiesis |
| --- | --- |
| Executor image and command | Pod composition, scheduling, lifecycle |
| Input and output URLs | Staging and upload |
| `TesResources` | Volume sizing, container resources |
| Kubernetes 1.29+, Postgres, object storage, an OIDC issuer | API, recorder, controller, schema |

## Pick a client

- **`curl`**: the fastest way to learn the API. The
  [Quickstart](./quickstart.md#submit-a-task) has working examples.
- **A workflow engine**: Nextflow, Snakemake, Sprocket and others. See
  [Workflow engines](../guides/workflow-engines.md).
- **Your own code**: the [TES API](../reference/api.md) is the contract;
  py-tes is a ready Python client.

## What Poiesis doesn't do

- **Schedule across clusters.** One TaskPod, one cluster.
- **Mutate your executor image.** Commands run exactly as submitted.
- **Cache anything.** Each submission is independent.
- **Run its own login flow.** Poiesis is a resource server, not an OAuth
  client. It validates tokens minted by an external identity provider
  (Keycloak, Auth0, Dex, …). See
  [Authentication](../concepts/authentication.md).
