---
description: Every task gets its own PersistentVolumeClaim, sized by disk_gb, mounted at the task's paths, and deleted with the task's Job.
---

# Task volumes

Every task gets its own volume, sized to what it asks for and deleted
after it.

<FlowDiagram :spec="{
  title: 'Task volume lifecycle',
  h: 212,
  nodes: {
    rq: { x: 4, y: 44, w: 112, label: 'Task request', sub: 'disk_gb: 25' },
    api: { x: 154, y: 44, w: 112, label: 'Poiesis API', sub: 'max 100 Gi' },
    pvc: { x: 304, y: 44, w: 112, label: 'Volume', sub: '25 Gi' },
    bad: { x: 154, y: 150, w: 112, label: '400', sub: 'over the limit' },
    job: { x: 304, y: 150, w: 112, label: 'Job', sub: 'owns the volume' }
  },
  edges: [['rq','api'],['api','pvc'],['api','bad'],['job','pvc']],
  hops: [
    { f: 'rq', t: 'api', label: 'disk_gb: 25', cap: 'A task asks for 25 Gi with resources.disk_gb.' },
    { f: 'api', t: 'pvc', label: 'create', tone: 'ok', cap: 'Under maxSizeGi, Poiesis creates a 25 Gi volume for it.' },
    { f: 'api', t: 'bad', label: 'disk_gb: 500', tone: 'bad', cap: 'Over the limit: 400, before any Pod starts.' },
    { f: 'job', t: 'pvc', label: 'owner', cap: 'The Job of the task owns the volume.' },
    { f: 'job', t: 'pvc', label: 'delete', cap: 'After retainAfterSeconds the Job is deleted, and the volume with it.' }
  ]
}" />

- One `PersistentVolumeClaim` per task, shared by all its containers.
- Sized by the task's `resources.disk_gb`. Over `maxSizeGi`, the request
  gets `400` before any Pod starts.
- Owned by the task's Job, so Kubernetes deletes both together.

## Settings

All keys are under `taskpods.persistence`:

| Key | Default | What it does |
| --- | --- | --- |
| `defaultSizeGi` | `10` | Size when the task asks for none. |
| `maxSizeGi` | `100` | Largest a task may ask for. The schema refuses an install without it. |
| `storageClass` | cluster default | `""` omits it (cluster default); `"-"` sets `storageClassName: ""` (no dynamic provisioning, needs a pre-bound PV); any other value names a StorageClass. |
| `accessModes` | `[ReadWriteOnce]` | Access modes of every task volume. |
| `retainAfterSeconds` | `3600` | `ttlSecondsAfterFinished` of the task's Job. `null` keeps the Job and volume until deleted by hand. |
| `labels` | `{}` | Labels on every task volume: cost allocation, backup selectors, data classification. |
| `annotations` | `{}` | Annotations on every task volume, e.g. for Velero or Kasten. |

```yaml
taskpods:
  persistence:
    defaultSizeGi: 20
    maxSizeGi: 500
    storageClass: fast-ssd
    labels: {backup: velero}
```

<Callout type="info">

A task runs on one node, so `ReadWriteOnce` is enough. If your storage
only offers ReadWriteMany (NFS, CephFS), set
`accessModes: [ReadWriteMany]`.

</Callout>

## Task paths

The volume is mounted at `/transfer` in every container but `ack`: there TIF stages
inputs and TOF collects outputs. Executors also see the volume at the
paths the task declares: each declared path is a mount of the same place
on the volume, so a file an executor writes under `/data` is the file TOF
uploads.

What is mounted:

- `volumes` and `DIRECTORY` inputs and outputs: the path itself.
- `FILE` inputs: the file itself, a single-file mount. It can be read and
  written in place, but not renamed or replaced (`mv tmp in.txt` fails),
  and nothing can be created below it.
- `FILE` outputs: their directory.
- Outputs with wildcards (`FILE` or `DIRECTORY`): the directory before
  the first wildcard (`/data` for `/data/*/x.txt`), whatever
  `path_prefix` is.

A path below another mounted path is covered by that mount. Only data
under these paths persists between executors and reaches TOF; anything
else an executor writes stays in its own container and is lost.

<Callout type="warn">

Poiesis doesn't create the directories of task `volumes`. A volume path
with a mount of its own appears (the kubelet creates mount points), but
one below another mounted path doesn't exist until an executor makes it.
An engine that expects an empty directory there (Sprocket does) may
fail; see [Sprocket](../guides/workflow-engines.md#sprocket).

</Callout>

A task is refused with `400 Bad Request` if a path:

- is relative;
- has a `..` component (`.` and repeated slashes are fine);
- would need a mount at `/` (for example `/` as a volume, or a wildcard
  in the first component, `/*.txt`);
- is in `/transfer`, where Poiesis stages task files;
- is below a `FILE` input;
- is at or below an operator mount (`taskpods.extraVolumeMounts`), such
  as a read-only reference volume.

## Reference data

Operators can mount shared data, such as a read-only reference genome,
into every task with `taskpods.extraVolumes` and
`taskpods.extraVolumeMounts`. The mounts reach executors too:

```yaml
taskpods:
  extraVolumes:
    - name: ref-grch38
      persistentVolumeClaim:
        claimName: ref-grch38-ro
        readOnly: true
  extraVolumeMounts:
    - name: ref-grch38
      mountPath: /ref/grch38
      readOnly: true
```

The names `task-data`, `postgres-ca` and `tmp` are reserved; the API
refuses to start with them. See [Helm values](../reference/helm-values.md#taskpods).

## Cleanup and OpenShift

The volume's ownerReference to its Job sets `blockOwnerDeletion: false`,
so the API's Role needs no `jobs/finalizers` permission, which OpenShift
project admins can't grant. Kubernetes' garbage collector deletes the
volume when the Job goes.
