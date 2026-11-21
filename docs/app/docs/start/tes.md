---
description: The GA4GH Task Execution Service in five minutes - what a task is, the five endpoints, and the states a task goes through.
---

# TES in 5 minutes

TES is a [GA4GH](https://www.ga4gh.org/) standard for a REST API that
submits, manages and monitors batch tasks. It was built to make genomic
analyses portable across compute environments, but any workload that
fits "run this command with these inputs and collect these outputs"
works. Poiesis implements the server side on Kubernetes.

## A task

A TES task declares:

- `executors`: an ordered list of image, command, environment and
  working directory;
- `inputs`: URLs to stage onto the task's volume (optional);
- `outputs`: paths to upload after the executors run (optional);
- `resources`: CPU, RAM and disk.

```json
{
  "name": "hello",
  "executors": [
    {"image": "alpine:3.20", "command": ["echo", "hello from poiesis"]}
  ]
}
```

## The API

Five operations under `/ga4gh/tes/v1`:

| Method | Path | Operation |
| --- | --- | --- |
| `GET` | `/service-info` | `GetServiceInfo` |
| `GET` | `/tasks` | `ListTasks` (filters, pagination, views) |
| `POST` | `/tasks` | `CreateTask` |
| `GET` | `/tasks/{id}` | `GetTask` (`MINIMAL`, `BASIC` or `FULL` view) |
| `POST` | `/tasks/{id}:cancel` | `CancelTask` |

The full contract is on the [TES API](../reference/api.md) page.

## States

<FlowDiagram :spec="{
  title: 'Task states',
  h: 200,
  nodes: {
    q: { x: 4, y: 20, w: 120, label: 'QUEUED' },
    r: { x: 150, y: 20, w: 120, label: 'RUNNING' },
    c: { x: 296, y: 20, w: 120, label: 'COMPLETE' },
    e: { x: 296, y: 130, w: 120, label: 'EXECUTOR_ERROR' },
    s: { x: 150, y: 130, w: 120, label: 'SYSTEM_ERROR' },
    x: { x: 4, y: 130, w: 120, label: 'CANCELED' }
  },
  edges: [['q','r'],['r','c'],['r','e'],['r','s'],['q','x']],
  hops: [
    { f: 'q', t: 'r', label: 'trec starts', cap: 'The task is QUEUED until its Pod starts. trec, the first container, marks it RUNNING, before inputs are staged.' },
    { f: 'r', t: 'c', label: 'exit 0', tone: 'ok', cap: 'Every executor succeeded and the outputs are uploaded: COMPLETE.' },
    { f: 'r', t: 'e', label: 'exit 1', tone: 'bad', cap: 'An executor failed: EXECUTOR_ERROR.' },
    { f: 'r', t: 's', label: 'OOMKill', tone: 'bad', cap: 'The infrastructure failed (OOMKill, eviction, node loss): SYSTEM_ERROR.' },
    { f: 'q', t: 'x', label: 'cancel', cap: 'A cancel at any point goes through CANCELING and ends in CANCELED.' }
  ]
}" />

Terminal states are `COMPLETE`, `EXECUTOR_ERROR`, `SYSTEM_ERROR` and
`CANCELED`. `SYSTEM_ERROR` covers failures that aren't your executor's:
an image that can't be pulled, a volume that can't be bound, a node that
disappears, an input or output that can't be staged. Poiesis doesn't use `INITIALIZING`, `PAUSED` or `PREEMPTED`:
a task stays `QUEUED` until its Pod starts, and is `RUNNING` from then on,
input staging included.

[Specification on GitHub](https://github.com/ga4gh/task-execution-schemas).
