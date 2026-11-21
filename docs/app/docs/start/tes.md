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
  h: 290,
  nodes: {
    q: { x: 4, y: 20, w: 120, label: 'QUEUED' },
    i: { x: 150, y: 20, w: 120, label: 'INITIALIZING' },
    s: { x: 296, y: 20, w: 120, label: 'SYSTEM_ERROR' },
    x: { x: 4, y: 130, w: 120, label: 'CANCELED' },
    r: { x: 150, y: 130, w: 120, label: 'RUNNING' },
    c: { x: 296, y: 130, w: 120, label: 'COMPLETE' },
    e: { x: 150, y: 240, w: 120, label: 'EXECUTOR_ERROR' }
  },
  edges: [['q','i'],['i','r'],['i','s'],['r','c'],['r','e'],['r','s'],['q','x']],
  hops: [
    { f: 'q', t: 'i', label: 'trec starts', cap: 'The task is QUEUED until its Pod is scheduled. trec, the first container, marks it INITIALIZING while images are pulled and inputs staged.' },
    { f: 'i', t: 'r', label: 'exec-0 starts', cap: 'Inputs are staged and the first executor has started: RUNNING.' },
    { f: 'i', t: 's', label: 'tif fails', tone: 'bad', cap: 'An input that fails to stage, or an image that fails to pull: SYSTEM_ERROR.' },
    { f: 'r', t: 'c', label: 'exit 0', tone: 'ok', cap: 'Every executor succeeded and the outputs are uploaded: COMPLETE.' },
    { f: 'r', t: 'e', label: 'exit 1', tone: 'bad', cap: 'An executor failed: EXECUTOR_ERROR.' },
    { f: 'r', t: 's', label: 'OOMKill', tone: 'bad', cap: 'The infrastructure failed (OOMKill, eviction, node loss): SYSTEM_ERROR.' },
    { f: 'q', t: 'x', label: 'cancel', cap: 'A cancel at any point goes through CANCELING and ends in CANCELED.' }
  ]
}" />

Terminal states are `COMPLETE`, `EXECUTOR_ERROR`, `SYSTEM_ERROR` and
`CANCELED`. `SYSTEM_ERROR` covers failures that aren't your executor's:
an image that can't be pulled, a volume that can't be bound, a node that
disappears, an input or output that can't be staged.

- A task is `QUEUED` until its Pod is scheduled and `trec` starts.
- It is `INITIALIZING` from then until the first executor starts:
  images are pulled and `tif` stages the inputs. A task without inputs
  passes through `INITIALIZING` too, usually for the time it takes to
  pull the first executor's image.
- It is `RUNNING` from the start of the first executor until it ends,
  output upload included.

Poiesis doesn't use `PAUSED` or `PREEMPTED`.

## Fields Poiesis accepts but ignores

- `inputs[].streamable`: TES lets a server ignore it. `tif` always
  downloads an input onto the task's volume; nothing is streamed or
  FUSE-mounted.

[Specification on GitHub](https://github.com/ga4gh/task-execution-schemas).
