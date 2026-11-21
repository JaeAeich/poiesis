---
description: How tif stages inputs and tof uploads outputs - supported URL schemes, S3 configuration, glob outputs and presigned HTTP uploads.
---

# Storage and staging

Only inputs and outputs touch your storage. `tif` copies each input onto
the task's volume before the executors run; `tof` uploads each output
after they finish.

<FlowDiagram :spec="{
  title: 'Staging inputs and outputs',
  h: 260,
  nodes: {
    in: { x: 10, y: 30, w: 100, label: 's3://in' },
    tif: { x: 155, y: 30, w: 110, label: 'tif', sub: 'stage in' },
    vol: { x: 155, y: 115, w: 110, label: 'volume' },
    tof: { x: 155, y: 200, w: 110, label: 'tof', sub: 'stage out' },
    out: { x: 310, y: 200, w: 100, label: 's3://out' },
    cr: { x: 310, y: 30, w: 100, label: 'credentials', sub: 'Secret or IRSA' }
  },
  edges: [['cr','tif'],['in','tif'],['tif','vol'],['vol','tof'],['tof','out']],
  hops: [
    { f: 'cr', t: 'tif', label: 'AWS_*', cap: 'tif gets the S3 credentials from a Secret or workload identity.' },
    { f: 'in', t: 'tif', label: 'reads.fq', cap: 'It downloads each input...' },
    { f: 'tif', t: 'vol', label: 'reads.fq', cap: '...onto the volume of the task.' },
    { f: 'vol', t: 'tof', label: 'sorted.bam', cap: 'After the executors, tof picks up the outputs...' },
    { f: 'tof', t: 'out', label: 'sorted.bam', tone: 'ok', cap: '...and uploads them.' }
  ]
}" />

- Inputs: `s3://`, `http://`, `https://`, `file://` and inline `content`.
- Outputs: `s3://`, `http://`, `https://` and `file://`.
- Inline content as an output, or an unknown scheme, is refused with
  `400`. `GET /service-info` lists the supported schemes.

## Common patterns

- **No IO**: executors only. Useful to smoke-test image pulls and
  scheduling.
- **S3 in, S3 out**: `inputs[]` and `outputs[]` point at object storage.
- **Inline content**: `inputs[].content` carries the file body; no
  external storage needed.
- **Multi-executor**: executors run in order; data persists between them
  only under the task's [paths](./task-volumes.md#task-paths).

## S3

Point Poiesis at any S3-compatible store (AWS S3, Ceph, SeaweedFS, MinIO):

```yaml
s3:
  endpoint: ""            # AWS_ENDPOINT_URL; empty for AWS
  region: eu-central-1    # AWS_REGION
  existingSecret: poiesis-s3
```

The Secret holds `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. The
chart never creates it:

```bash
kubectl -n poiesis create secret generic poiesis-s3 \
  --from-literal=AWS_ACCESS_KEY_ID=… \
  --from-literal=AWS_SECRET_ACCESS_KEY=…
```

On EKS, leave `existingSecret` empty and give the service accounts an IAM
role through IRSA instead:

```yaml
serviceAccount:
  api:
    annotations:
      eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/poiesis
  taskpod:
    annotations:
      eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/poiesis
```

<Callout type="info">

Poiesis talks to storage with AWS credentials. Google Cloud Storage works
through its S3-compatible API with HMAC keys in the Secret. Native GCS,
Azure Blob and FTP are planned
([#29](https://github.com/jaeaeich/poiesis/issues/29)), as are FUSE
mounts ([#27](https://github.com/jaeaeich/poiesis/issues/27)).

</Callout>

## Glob outputs

An output whose `path` has wildcards, such as `/outputs/*.vcf`, uploads
every file and directory that matches, each under its path relative to
`path_prefix` (inferred from the path when unset). Patterns follow
Python's `glob`: `*`, `?` and `[...]`; `**` matches one level only, and
`{a,b}` is not expanded.

If the glob matches no file, `tof` uploads nothing for that output and
logs a warning naming it; the task still succeeds.

<Callout type="warn">

`taskpods.outputGlobFallback: true` makes `tof` upload every file under
`path_prefix` instead, for clients whose patterns don't match the files
they mean. That can export far more than the client asked for. It is off
by default.

</Callout>

## HTTP(S) outputs

An `outputs[].url` can be an `http://` or `https://` URL that grants
access by itself, such as a presigned upload URL from Amazon S3 or Google
Cloud Storage, so `tof` needs no credentials for the client's storage.
`tof` streams each file from disk in a `PUT` request with a
`Content-Length` header, as presigned upload URLs require.

- A presigned URL is signed for one object, so use one `FILE` output per
  presigned URL.
- For a `DIRECTORY` or glob output, `tof` derives each file's URL by
  appending the file's relative path, escaped, to the path of the output
  URL, keeping its query string. Those URLs carry no valid signature, so
  point the output URL at a server that signs each upload as it arrives
  and redirects it to the storage provider.
- If a glob matches no file, `tof` uploads nothing (see
  [Glob outputs](#glob-outputs)). With `outputGlobFallback` on, it
  uploads every file under `path_prefix` instead, and behind a signing
  server all of those files are signed and stored.

Responses:

| Response | What `tof` does |
| --- | --- |
| `2xx` | Done. |
| `307`, `308` | Sends the file again to the new URL, unless the output URL is `https://` and the new one isn't. The first request carries the file too, so up to the whole file reaches a redirecting server. |
| `301`, `302`, `303` | Fails: following would turn the `PUT` into a `GET`. |
| `429`, `500`, `502`, `503`, `504`, connection error, timeout | Retries twice, after 1 s and 2 s, each time from the output URL. |
| Anything else | Fails; the `tof` log shows the start of the response body. |

- `tof` sets no size limit, but providers cap a single `PUT`: 5 GB on
  Amazon S3.
- `tof` connects to whatever host the output URL or a redirect names,
  from the TaskPod's network, as executors can. To limit where tasks send
  data, restrict egress from the task namespace with a NetworkPolicy.
- Over `http://`, the URL (including any signature) and the file travel
  unencrypted; use `https://` outside a trusted network.
- The URL is stored with the task, including any signature in its query
  string, so issue presigned URLs with a short expiry.
