---
description: How tif stages inputs and tof uploads outputs - supported URL schemes, S3, Google Cloud Storage and Azure Blob configuration, workload identity, FTP and DRS, glob outputs and presigned HTTP uploads.
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
    cr: { x: 310, y: 30, w: 100, label: 'credentials', sub: 'Secret or identity' }
  },
  edges: [['cr','tif'],['in','tif'],['tif','vol'],['vol','tof'],['tof','out']],
  hops: [
    { f: 'cr', t: 'tif', label: 'keys', cap: 'tif gets the storage credentials from a Secret or workload identity.' },
    { f: 'in', t: 'tif', label: 'reads.fq', cap: 'It downloads each input...' },
    { f: 'tif', t: 'vol', label: 'reads.fq', cap: '...onto the volume of the task.' },
    { f: 'vol', t: 'tof', label: 'sorted.bam', cap: 'After the executors, tof picks up the outputs...' },
    { f: 'tof', t: 'out', label: 'sorted.bam', tone: 'ok', cap: '...and uploads them.' }
  ]
}" />

- Inputs: `s3://`, `http://`, `https://`, `ftp://`, `ftps://` and inline
  `content`.
- Outputs: `s3://`, `http://`, `https://`, `ftp://` and `ftps://`.
- `ftp://` and `ftps://` are on unless the operator turns them off (see
  [FTP](#ftp)).
- `drs://` (GA4GH DRS) for inputs, only where the operator turns it on
  (see [DRS](#drs)).
- `gs://` (Google Cloud Storage) and `az://` (Azure Blob Storage) for
  both, only where the operator turns them on
  (see [Object stores](#object-stores)).
- `file://` for both, only where the operator turns it on
  (see [Local paths](#local-paths)).
- Inline content as an output, or an unknown scheme, is refused with
  `400`. `GET /service-info` lists the schemes this deployment accepts.
- Also refused with `400` at submit, since they would only fail in the
  Pod: an input with neither `url` nor `content`, a `DIRECTORY` input
  over `http(s)://`, `drs://` or as inline `content`, an `s3://`, `gs://`
  or `az://` URL whose provider the operator hasn't turned on, an FTP URL
  where FTP is off, and a `drs://` URI that DRS is off for, whose host
  isn't allowed, or that is a compact identifier.

## Common patterns

- **No IO**: executors only. Useful to smoke-test image pulls and
  scheduling.
- **Object store in, object store out**: `inputs[]` and `outputs[]`
  point at `s3://`, `gs://` or `az://` URLs.
- **Inline content**: `inputs[].content` carries the file body; no
  external storage needed. An input with non-empty `content` ignores its
  `url`, as TES requires.
- **Multi-executor**: executors run in order; data persists between them
  only under the task's [paths](./task-volumes.md#task-paths).

## Object stores

`tif` and `tof` reach S3, Google Cloud Storage and Azure Blob Storage
through one code path, built on
[obstore](https://developmentseed.org/obstore/). A URL names a bucket
(for Azure, a container) and a key:

| Scheme  | URL                   | Tested end to end (kind, in CI)                                                                                |
| ------- | --------------------- | -------------------------------------------------------------------------------------------------------------- |
| `s3://` | `s3://bucket/key`     | SeaweedFS: `FILE` and `DIRECTORY` in and out, a 20 MiB upload in parts.                                        |
| `gs://` | `gs://bucket/key`     | fake-gcs-server: `FILE` and `DIRECTORY` in and out. Uploads in parts are not covered: the emulator lacks them. |
| `az://` | `az://container/blob` | Azurite: `FILE` and `DIRECTORY` in and out, a 20 MiB upload in parts.                                          |

These are emulators. CI does not run against AWS, Google Cloud or Azure,
and workload identity is tested with unit tests only (against a mocked
token service for Google). The per-cloud guides
([AWS](../guides/aws.md), [Google Cloud](../guides/gcp.md),
[Azure](../guides/azure.md)) list the setup.

A provider is off until the operator turns it on. While it is off, its
scheme is refused at submit with `400` and isn't listed in
`GET /service-info`. Each provider has one default store (the `s3`, `gcs`
and `azure` blocks below); [several stores](#several-stores) can serve
different buckets with different endpoints and credentials.

How `tif` and `tof` handle keys:

- The key is used as written. `?`, `#`, `[`, `{` and `*` are part of
  the key; a `FILE` input fetches exactly that object.
- A `DIRECTORY` input downloads every object below the key, in whole path
  segments: `s3://b/in` takes `in/a.txt`, not `in2/a.txt`. A `DIRECTORY`
  input that matches no object fails the task.
- Folder markers are skipped: keys ending in `/`, and a key that is also
  the directory of other keys.
- A key that would land outside the input's directory, such as
  `in/../x`, fails the task. Nothing is written outside the input's path.
- A `DIRECTORY` or glob output uploads each file below the URL's key
  plus the file's relative path. If the output URL itself has wildcards
  (`s3://b/out/*.vcf`), files go below the part before them (`out/`).
- Up to 4 files of a `DIRECTORY` or glob move at once. Downloads stream
  to disk. Large uploads go in parts, 4 at a time.
- A `5xx` response, a dropped connection or a timeout is retried up to 10
  times with exponential backoff, for at most 3 minutes per request.

### S3

Point Poiesis at AWS S3 or an S3-compatible store (Ceph, SeaweedFS,
MinIO):

```yaml
s3:
  endpoint: "" # AWS_ENDPOINT_URL; empty for AWS
  region: eu-central-1 # AWS_REGION
  existingSecret: poiesis-s3
```

S3 is on when any of `existingSecret`, `roleArn`, `anonymous: true` or
`enabled: true` is set. Other settings:

| Value                     | Default | Meaning                                                                                                                                         |
| ------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `s3.virtualHostedStyle`   | `false` | `true` sends `https://<bucket>.<endpoint>/<key>`. `false` sends path-style `https://<endpoint>/<bucket>/<key>`, which SeaweedFS and MinIO need. |
| `s3.serverSideEncryption` | `""`    | `AES256` (SSE-S3), `aws:kms` (SSE-KMS) or `aws:kms:dsse`, for every upload.                                                                     |
| `s3.kmsKeyId`             | `""`    | KMS key for `aws:kms`; empty uses the bucket's default key.                                                                                     |
| `s3.requesterPays`        | `false` | Pay for requests to requester-pays buckets.                                                                                                     |
| `s3.anonymous`            | `false` | Unsigned requests, for public buckets. No keys or role.                                                                                         |

An `http://` endpoint is allowed; use `https://` outside a trusted
network.

**Static keys.** The Secret holds `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`, and optionally `AWS_SESSION_TOKEN` for temporary
credentials. The chart never creates it:

```bash
kubectl -n poiesis create secret generic poiesis-s3 \
  --from-literal=AWS_ACCESS_KEY_ID=… \
  --from-literal=AWS_SECRET_ACCESS_KEY=…
```

`trec`, `tif` and `tof` read these keys from the Secret by reference
(`secretKeyRef`), so the values are not in the Job or Pod spec. Executors
do not get them. The endpoint and region are not secret and are set as
plain values.

A Pod can only read Secrets in its own namespace. If `taskpods.namespace`
is not the release namespace, create the Secret there as well; the chart
does not copy it. Use `taskpods.s3Secret` if it has a different name in
the task namespace:

```yaml
taskpods:
  namespace: poiesis-tasks
  s3Secret: poiesis-s3 # default: s3.existingSecret
```

If the Secret is missing in the task namespace, no TaskPod can start, not
only the ones that use `s3://`.

**Workload identity on EKS (IRSA).** Set the role and leave
`existingSecret` empty:

```yaml
s3:
  region: eu-central-1
  roleArn: arn:aws:iam::123456789012:role/poiesis-filer
```

The API then adds a ServiceAccount token for the audience
`sts.amazonaws.com` to each TaskPod and mounts it into `tif` and `tof`
only, with `AWS_ROLE_ARN` and `AWS_WEB_IDENTITY_TOKEN_FILE` pointing at
it. They trade it for the role's credentials at AWS STS.

1. Create an IAM OIDC provider for the cluster, as for any IRSA setup.
2. Give the role a trust policy for that provider with the subject
   `system:serviceaccount:<taskpod namespace>:<taskpod ServiceAccount>`
   (by default `<release>-poiesis-taskpod`) and the audience
   `sts.amazonaws.com`.
3. Grant the role `s3:GetObject`, `s3:PutObject` and `s3:ListBucket` on
   the buckets tasks use, and `kms:Decrypt` / `kms:GenerateDataKey` if
   they are encrypted with SSE-KMS.

<Callout type="warn">

Don't annotate the TaskPod ServiceAccount with
`eks.amazonaws.com/role-arn`. The EKS webhook would then inject the token
into every container of the TaskPod, executors included, and any user
image could act as the role.

</Callout>

**Instance credentials.** With `s3.enabled: true` and neither keys nor a
role, `tif` and `tof` use the default chain: the EC2 instance role through
IMDS, or EKS Pod Identity if its agent injects credentials. Executors on
the same node can usually reach IMDS too, so prefer `roleArn`.

### Google Cloud Storage

GCS needs a key, Workload Identity Federation or `anonymous: true`
(unsigned requests, public buckets only). With none, `tif` and `tof`
would ask the node's metadata server, which executors can reach too, so
the chart refuses it.

**Service account key.**

```yaml
gcs:
  enabled: true
  existingSecret: poiesis-gcs # in the TaskPod namespace
```

The Secret holds a service account's JSON key under
`GOOGLE_SERVICE_ACCOUNT_KEY`. It reaches `tif` and `tof` only, by
reference:

```bash
kubectl -n <taskpod namespace> create secret generic poiesis-gcs \
  --from-file=GOOGLE_SERVICE_ACCOUNT_KEY=key.json
```

**Workload Identity Federation.** Name a workload identity pool provider
that trusts the cluster's OIDC issuer, and leave `existingSecret` empty:

```yaml
gcs:
  enabled: true
  workloadIdentityProvider: //iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/poiesis/providers/cluster
  serviceAccount: poiesis-filer@my-project.iam.gserviceaccount.com # optional
```

The API adds a ServiceAccount token for the audience
`https:<workloadIdentityProvider>` to each TaskPod and mounts it into
`tif` and `tof` only. They send it to Google STS
(`sts.googleapis.com`) for a federated token and, when `serviceAccount`
is set, trade that for the service account's token
(`iamcredentials.googleapis.com`, scope `devstorage.read_write`). Tokens
are renewed 5 minutes before they expire. Without `serviceAccount`,
grant the bucket roles to the federated principal itself.

This does not use GKE's built-in Workload Identity (the
`iam.gke.io/gcp-service-account` annotation): that serves tokens from the
node's metadata server to every container of the Pod, executors
included. Don't annotate the TaskPod ServiceAccount with it. See
[Google Cloud](../guides/gcp.md) for the pool and provider setup.

**Endpoint.** `gcs.endpoint` replaces `https://storage.googleapis.com`,
for Private Service Connect or an emulator. An `http://` endpoint is
allowed. STS and IAM Credentials are always the public Google endpoints.

GCS also works through its S3-compatible API with HMAC keys as `s3:`
settings.

### Azure Blob Storage

```yaml
azure:
  enabled: true
  accountName: poiesisdata
  existingSecret: poiesis-azure # or the workload identity below
```

`az://container/blob` names a blob in that account. The Secret, in the
TaskPod namespace, holds `AZURE_STORAGE_ACCOUNT_KEY` or
`AZURE_STORAGE_SAS_TOKEN`. Both keys are optional in the Secret; put in
the one you have. A SAS token can be pasted with or without its leading
`?`; it needs read, write and list permissions on the containers tasks
use, and tasks fail once it expires.

```bash
kubectl -n <taskpod namespace> create secret generic poiesis-azure \
  --from-literal=AZURE_STORAGE_SAS_TOKEN='sv=…&sig=…'
```

`azure.anonymous: true` sends unsigned requests, for containers with
public read access; leave `existingSecret` and `clientId` empty.

`azure.endpoint` replaces `https://<accountName>.blob.core.windows.net`,
for a private endpoint with a custom DNS name, a sovereign cloud (for
example `https://<account>.blob.core.chinacloudapi.cn`), Azure Stack Hub
or Azurite (`http://azurite:10000/<account>`). An `http://` endpoint is
allowed.

**Workload identity on AKS.** Set the managed identity's client ID and
its tenant, and leave `existingSecret` empty:

```yaml
azure:
  enabled: true
  accountName: poiesisdata
  clientId: 00000000-0000-0000-0000-000000000000
  tenantId: 00000000-0000-0000-0000-000000000000
```

The API adds a ServiceAccount token for the audience
`api://AzureADTokenExchange` to each TaskPod and mounts it into `tif` and
`tof` only, with `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and
`AZURE_FEDERATED_TOKEN_FILE`.

1. Enable the cluster's OIDC issuer.
2. Add a federated credential to the managed identity with that issuer,
   the subject
   `system:serviceaccount:<taskpod namespace>:<taskpod ServiceAccount>`
   and the audience `api://AzureADTokenExchange`.
3. Give the identity `Storage Blob Data Contributor` on the account or
   its containers.

Don't add the `azure.workload.identity/use` label or the
`azure.workload.identity/client-id` annotation: the AKS webhook would
inject the token into every container, executors included.

### Several stores

`objectStores` adds named stores next to the default ones. Each has a
provider, the buckets it serves (containers, for Azure), and the same
options as that provider's default block, without `enabled`. For
example, public data on AWS, a lab's Ceph with its own keys, and
everything else on the default S3 store:

```yaml
s3:
  region: eu-central-1
  existingSecret: poiesis-s3 # the default store
objectStores:
  - name: aws-open-data
    provider: s3
    buckets: ["1000genomes", "gnomad-public-*"]
    region: us-east-1
    anonymous: true
  - name: ceph
    provider: s3
    buckets: ["lab-*"]
    endpoint: https://ceph.example.org
    existingSecret: poiesis-ceph
```

| URL                       | Store           | Credentials              |
| ------------------------- | --------------- | ------------------------ |
| `s3://1000genomes/…`      | `aws-open-data` | none (unsigned requests) |
| `s3://gnomad-public-v4/…` | `aws-open-data` | none (unsigned requests) |
| `s3://lab-results/…`      | `ceph`          | Secret `poiesis-ceph`    |
| `s3://anything-else/…`    | default `s3`    | Secret `poiesis-s3`      |

How a URL finds its store:

- A pattern is a bucket name, or a prefix ending in `*` (`*` alone takes
  every bucket). Matching is case sensitive.
- The named store of the URL's provider whose patterns match the bucket
  serves it. Otherwise the provider's default store does, if it is on.
  Otherwise the task is refused at submit with `400` naming the bucket.
- Patterns of two stores of one provider may not overlap (`lab-*` and
  `lab-archive`, say). The API refuses to start and names both stores.
  The same bucket name under two providers is fine.
- The URL stays `s3://bucket/key`: TES requests don't name a store, and
  `GET /service-info` lists schemes only, not store names.
- `drs://` inputs that resolve to an object-store URL go through the same
  lookup. An access method whose bucket no store serves is skipped.

Credentials stay as for the default stores, per store:

- `existingSecret` is a Secret in the TaskPod namespace with the
  provider's usual keys (`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`,
  `GOOGLE_SERVICE_ACCOUNT_KEY`, or `AZURE_STORAGE_ACCOUNT_KEY` /
  `AZURE_STORAGE_SAS_TOKEN`). `tif` and `tof` read them by reference, as
  `POIESIS_STORE_<NAME>_<KEY>`; `trec` and executors get nothing.
- `roleArn` (S3), `clientId` and `tenantId` (Azure) and
  `workloadIdentityProvider` (GCS) use workload identity, as above. One
  ServiceAccount token is mounted per audience: every AWS role shares
  one, every Azure identity shares one, each Google pool provider gets
  its own.
- `anonymous: true` sends unsigned requests and takes no credentials.
  A store sets one credential source at most. A named S3 store with none
  uses the node's instance credentials, as `s3.enabled: true` does.
- A named store never sees the default store's settings: its endpoint,
  region and keys are only its own.

The store table (no secret values) reaches `tif` and `tof` as one JSON
value, `POIESIS_OBJECT_STORES`.

<Callout type="info">

All three stores share one code path. The end-to-end tests run it against
emulators, not the real cloud services. SFTP is not supported. FUSE
mounts are planned
([#27](https://github.com/jaeaeich/poiesis/issues/27)).

</Callout>

## FTP

`ftp://` and `ftps://` URLs work for inputs (`FILE` and `DIRECTORY`) and
outputs (`FILE`, `DIRECTORY` and glob), for public archives such as EBI,
ENA and NCBI:

```json
{ "url": "ftp://ftp.ebi.ac.uk/pub/databases/…/genome.fa.gz", "path": "/data/genome.fa.gz" }
```

- Passive mode, binary transfers. `ftps://` is explicit TLS (`AUTH TLS`),
  with the server's certificate checked; implicit TLS (port 990) is not
  supported.
- A URL with no user logs in as `anonymous`. `ftp://user:password@host/…`
  logs in with those.
- The path is relative to the login directory, as in RFC 1738; on public
  archives that is the server's root. Start it with `%2F` for an absolute
  path.
- A `DIRECTORY` input downloads everything under the directory. Names in
  the server's listing are reduced to their last path segment, and `.`
  and `..` are skipped, so nothing lands outside the input's path.
- A `FILE` input is written to a temporary file next to its path and
  renamed into place once complete.
- An upload creates the directories it needs.
- A dropped or refused connection, a timeout or a `4xx` reply is retried
  twice, after 1 s and 2 s. A `5xx` reply fails at once: `550` for a file
  that is missing or not readable, `530` for a rejected login. The
  task's `system_logs` show the reply.

<Callout type="warn">

Credentials in an FTP URL are stored with the task, like the rest of the
URL, and anyone who can read the task can read them. Logs, termination
messages and `logs[].outputs` leave them out. Plain `ftp://` sends them
unencrypted; use `ftps://` where the server has it.

</Callout>

The operator turns FTP off with `taskpods.ftp.enabled: false`; tasks
using it then get a `400`, and `GET /service-info` doesn't list it.

## DRS

`drs://` inputs name an object on a
[GA4GH DRS](https://ga4gh.github.io/data-repository-service-schemas/)
1.x server, as a hostname-based URI: `drs://<host>/<object_id>`. DRS is
off by default:

```yaml
taskpods:
  drs:
    enabled: true
    allowedHosts: ["drs.example.org"] # empty: any host
    existingSecret: poiesis-drs # optional, key DRS_BEARER_TOKEN
```

`tif` resolves the URI, then stages the URL it gets like any other input:

1. `GET https://<host>/ga4gh/drs/v1/objects/<object_id>`.
2. It picks the first access method whose URL this deployment can stage:
   `https`, then `s3`, `gs` or `az` where a store of this deployment
   serves the bucket ([several stores](#several-stores)), then `ftps`,
   `ftp` and `http`.
3. For an `access_id`, it gets the URL from
   `/objects/<object_id>/access/<access_id>`. Headers in that answer go
   with the data request (not to another host after a redirect). An
   object-store or FTP URL that needs headers is skipped.

- The bearer token from `existingSecret` goes to the DRS server only,
  never to the data URL. It reaches `tif` by reference; `tof`, `trec` and
  executors don't get it.
- Refused with `400` at submit: `drs://` while DRS is off, a host not in
  `allowedHosts`, a compact-identifier URI (`drs://namespace:accession`)
  and a `DIRECTORY` input.
- Fails the task in `tif`: a bundle (an object with `contents`), an
  unknown object (`404`), access denied (`401`, `403`), or no access
  method this deployment can stage.
- `drs://` can't be an output: DRS has no upload API.

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

An output that is a symlink pointing outside the task volume, or a
directory holding one, fails the task: `tof` would otherwise follow the
link into its own container. Links that stay inside the volume are fine.

## Local paths

`file://` URLs are off by default; a task that uses one gets a `400`.
A `file://` path is read or written inside `tif` and `tof`, not on the
client's machine, so it is only useful for data the operator mounts into
TaskPods, such as a shared reference volume.

```yaml
taskpods:
  extraVolumes:
    - name: reference
      persistentVolumeClaim: { claimName: reference-data }
  extraVolumeMounts:
    - name: reference
      mountPath: /mnt/reference
      readOnly: true
  fileUrlRoots: ["/mnt/reference"]
```

- A URL must name a path under one of `fileUrlRoots`; anything else is
  refused with `400`.
- `tif` and `tof` resolve symlinks before they read or write, and stop
  if the real path leaves those directories.
- `GET /service-info` lists `file://` only when it is on.

## HTTP(S) inputs

`tif` downloads an `http://` or `https://` input with a `GET` request. It
stages the input only from a `2xx` response. The body goes to a temporary
file next to the input's path and is renamed into place once it is
complete, so a failed download leaves no file at the input's path.

| Response                                                                     | What `tif` does                                                                                     |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `2xx`                                                                        | Stages the body as the input.                                                                       |
| `301`, `302`, `303`, `307`, `308`                                            | Follows up to 10 redirects, unless the request has reached an `https://` URL and the new one isn't. |
| `429`, `500`, `502`, `503`, `504`, connection error, timeout, body cut short | Retries twice, after 1 s and 2 s, each time from the input URL.                                     |
| Anything else                                                                | Fails the task; nothing is staged. An expired presigned URL answers `403`.                          |

A failed download ends the task in `SYSTEM_ERROR` (see
[Staging failures](#staging-failures)). Directories can't be downloaded
over HTTP(S).

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

| Response                                                     | What `tof` does                                                                                                                                                                                            |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `2xx`                                                        | Done.                                                                                                                                                                                                      |
| `307`, `308`                                                 | Sends the file again to the new URL, unless the request has reached an `https://` URL and the new one isn't. The first request carries the file too, so up to the whole file reaches a redirecting server. |
| `301`, `302`, `303`                                          | Fails: following would turn the `PUT` into a `GET`.                                                                                                                                                        |
| `429`, `500`, `502`, `503`, `504`, connection error, timeout | Retries twice, after 1 s and 2 s, each time from the output URL.                                                                                                                                           |
| Anything else                                                | Fails; the task's `system_logs` and the `tof` log show the start of the response body.                                                                                                                     |

- `tof` sets no size limit, but providers cap a single `PUT`: 5 GB on
  Amazon S3.
- `tof` connects to whatever host the output URL or a redirect names,
  from the TaskPod's network, as executors can. To limit where tasks send
  data, restrict egress from the task namespace with a NetworkPolicy.
- Over `http://`, the URL (including any signature) and the file travel
  unencrypted; use `https://` outside a trusted network.
- The URL is stored with the task, including any signature in its query
  string, so issue presigned URLs with a short expiry.

## Output file logs

Once every output is uploaded, `tof` stores one entry per uploaded file
in the task's `logs[].outputs`, shown in the `BASIC` and `FULL` views:

| Field        | Value                                                                    |
| ------------ | ------------------------------------------------------------------------ |
| `path`       | The file's path in the executor, e.g. `/outputs/dir/a.txt`.              |
| `size_bytes` | The file's size, as a string.                                            |
| `url`        | Where the file was uploaded, without the URL's query string or fragment. |

- A `DIRECTORY` or glob output gives one entry per file under it, each
  with the URL that file went to.
- The query of a presigned URL is its signature, so it is not stored in
  the entry. The output's own `url` in `outputs[]` keeps it, as submitted.
- A `tof` that runs again replaces the entries; it doesn't add more.
- If `tof` can't store the entries, it fails and the task ends in
  `SYSTEM_ERROR`, though its files are uploaded: a `COMPLETE` task
  always has its file list.

## Staging failures

When `tif` or `tof` fails, the task's `system_logs` say why. The filer
writes one line to its container's termination message, and TCtl copies
it into the log:

```text
container tif exited with code 1: input /inputs/reads.fq: HTTPError: GET https://bucket.example/reads.fq returned 403: <Error><Code>AccessDenied</Code>...
```

The line is at most 1 KiB. Query strings and the credentials of a URL
are cut from it, since the query of a presigned URL is its signature.

| What failed                                                                                        | Task state       |
| -------------------------------------------------------------------------------------------------- | ---------------- |
| Storage unreachable, a `5xx`, a timeout                                                            | `SYSTEM_ERROR`   |
| Access denied, an expired or rejected URL, a missing input                                         | `SYSTEM_ERROR`   |
| A full task volume, or the task can't be read from or its output file logs written to the database | `SYSTEM_ERROR`   |
| A declared output the executors didn't produce                                                     | `EXECUTOR_ERROR` |

The rule: a failed filer is `SYSTEM_ERROR`, because no executor failed.
The one exception is an output whose `path` isn't on the task's volume
when `tof` runs, or is a file where a `DIRECTORY` was declared. The
executors didn't produce what the task declared, so the task ends in
`EXECUTOR_ERROR` and the log names the output:

```text
container tof exited with code 1: output /outputs/sorted.bam was not produced by the executors
```

A glob that matches no file is not a failure (see
[Glob outputs](#glob-outputs)).
