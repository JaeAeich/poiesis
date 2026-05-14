# Poiesis

A [GA4GH TES `v1.1.0`](https://github.com/ga4gh/task-execution-schemas)
implementation for Kubernetes. One container image, one PostgreSQL
schema, no broker.

![Poiesis high-level overview](/diagrams/overview.svg)

Each TES task runs as **one Kubernetes Pod** wrapped in a `Job`. Init
containers carry the work; a [native sidecar](./glossary.md#task-recorder-trec)
records state. A leader-elected [controller](./glossary.md#task-controller-tctl)
backstops failures the sidecar can't self-report.

## Components

| Component | Role |
| --- | --- |
| **API** | FastAPI service exposing TES under `/ga4gh/tes/v1`. No scheduler, no reconciler. |
| **TaskPod** | One Pod per task: `trec` (sidecar) → `tif` → `exec-0..N` → `tof` → `ack`. |
| **TRec** | In-pod recorder. Watches the surrounding Pod, writes state and logs. |
| **TCtl** | Leader-elected Deployment. Reconciles OOMKill, eviction, node loss, unbindable PVC, pending timeout. |
| **Postgres** | Relational store. Conditional-UPDATE writer makes TRec/TCtl race-correct. |

## Filer protocols

`s3://`, `http://`, `https://`, `file://`, and inline `content`.

## What's yours vs what's ours

| You | Poiesis |
| --- | --- |
| Executor image + command | Pod composition, scheduling, lifecycle |
| Input/output URLs | Filer staging and upload |
| `TesResources` | PVC sizing, container resources |
| Kubernetes 1.29+ | API, recorder, controller, schema |

Executor images run verbatim — no wrapping, no rewriting, no injection.
