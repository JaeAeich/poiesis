---
description: Point Nextflow, Snakemake, Sprocket, cwl-tes, py-tes or Cromwell at Poiesis - endpoints, API keys, storage and known issues, with what has been tested.
---

# Workflow engines

| Engine | Status | Checked with |
| --- | --- | --- |
| Nextflow (`nf-ga4gh`) | Tested | Nextflow 25.10.4, `nf-ga4gh` 1.5.0 |
| Snakemake (TES executor) | Tested | Snakemake 9.27.2, plugin 0.1.3 |
| py-tes | Tested | 1.1.4 |
| Sprocket | Partly tested: two workarounds | 0.34.1 |
| cwl-tes | Partly tested: API key as Basic password only | main branch |
| Cromwell | Not tested yet | |
| Toil | Not tested yet | |

Tested means real workflows ran end to end. Using another engine?
[Open an issue](https://github.com/jaeaeich/poiesis/issues/new?title=Engine%20support%3A%20)
or send a PR with the setup.

## Credentials

Workflow engines read one credential when they start and use it for the
whole run. Give them a Poiesis [API key](../concepts/api-keys.md), not an
access token: a token expires within the hour, a key lasts as long as
you minted it for (7 days by default, if your operator turned keys
on).

Mint a key first, from the Swagger UI at `<API URL>/docs` or with
`curl` (see [Minting a key](../concepts/api-keys.md#minting-a-key)), and
keep it out of version control. The examples use
`http://localhost:8000`, the port-forwarded
[dev stack](../start/quickstart.md).

| Engine | Bearer (preferred) | Basic (key as password) |
| --- | --- | --- |
| Nextflow (`nf-ga4gh`) | `tes.oauthToken` | `tes.basicUsername`, `tes.basicPassword` |
| Snakemake (TES executor) | `--tes-token` | `--tes-user`, `--tes-password` |
| cwl-tes | not usable (see below) | `--user`, `--password` |
| py-tes | `HTTPClient(token=…)` | `HTTPClient(user=…, password=…)` |
| Sprocket | `auth.type = "bearer"` | `auth.type = "basic"` |

Nextflow, Snakemake and py-tes were checked with both forms; Sprocket
with both.

## Nextflow

The [`nf-ga4gh`](https://github.com/nextflow-io/nf-ga4gh) plugin sends
`tes.oauthToken` as `Authorization: Bearer <token>` on every request:

```groovy
plugins {
  id 'nf-ga4gh'
}

process.executor = 'tes'
tes.endpoint = 'http://localhost:8000/ga4gh/tes'
tes.oauthToken = 'poi_k7H2pQ…'
```

The plugin appends `/v1` to `tes.endpoint`, so it ends in `/ga4gh/tes`.

Keep the key out of `nextflow.config` (it tends to get committed):
store it as a [Nextflow secret](https://www.nextflow.io/docs/latest/secrets.html)
and refer to it.

```bash
nextflow secrets set POIESIS_KEY poi_k7H2pQ…
```

```groovy
tes.oauthToken = secrets.POIESIS_KEY
```

Basic works too, with any user name:

```groovy
tes.basicUsername = 'nextflow'
tes.basicPassword = 'poi_k7H2pQ…'
```

Set only one of the two: both write the `Authorization` header. See
[Nextflow end to end](./nextflow.md) for storage and a full example.

## Snakemake

The [TES executor plugin](https://github.com/snakemake/snakemake-executor-plugin-tes)
(`pip install snakemake-executor-plugin-tes`) takes the key as
`--tes-token` and sends it as a bearer token:

```bash
snakemake --executor tes \
  --tes-url http://localhost:8000/ga4gh/tes \
  --tes-token poi_k7H2pQ… \
  --default-storage-provider s3 \
  --default-storage-prefix s3://poiesis-test/snakemake \
  --jobs 10
```

The plugin pins py-tes 0.4, which appends `/v1/tasks` to `--tes-url`,
so the URL ends in `/ga4gh/tes`, as for Nextflow. The token can also
come from the environment, which keeps it out of the shell history:
`export SNAKEMAKE_TES_TOKEN=poi_k7H2pQ…`. For Basic, use `--tes-user`
(any name) and `--tes-password poi_…` (or `SNAKEMAKE_TES_USER` and
`SNAKEMAKE_TES_PASSWORD`) instead.

TaskPods don't share a file system with the host running Snakemake, so
the executor needs remote storage such as S3 (`--default-storage-*`
and the matching storage plugin).

Things that trip runs up, none of them about the key:

- At the start of every job the plugin runs `pip install` for the
  storage plugin inside the TaskPod, so TaskPods need to reach PyPI
  (or a mirror), or use an image where that install is a no-op.
- When a job fails, plugin 0.1.3 tries to read
  `$GITHUB_WORKSPACE/funnel.log` and stops with `KeyError:
  'GITHUB_WORKSPACE'`; the job's own error is in the TaskPod's logs.
- The default `snakemake/snakemake` image is amd64-only; on arm64
  nodes pass an arm64 image with `--container-image`.

## cwl-tes

[cwl-tes](https://github.com/ohsu-comp-bio/cwl-tes) checks its
`--token` locally as an RS256-signed JWT before sending anything, so it
refuses an API key (`Token is not valid`). Send the key as a Basic
password instead:

```bash
cwl-tes --tes http://localhost:8000 \
  --user cwl-tes --password poi_k7H2pQ… \
  workflow.cwl inputs.yml
```

`--user` and `--password` are on cwl-tes's main branch but not in the
`0.3.0` release on PyPI; install from the repository until a release
includes them:

```bash
pip install git+https://github.com/ohsu-comp-bio/cwl-tes.git
```

## py-tes

[py-tes](https://github.com/ohsu-comp-bio/py-tes), the Python TES
client (also used by the Snakemake executor and cwl-tes), sends `token`
as a bearer token. Since 1.1 it takes the server's base URL and finds
`/ga4gh/tes/v1` itself (older versions need `<base URL>/ga4gh/tes`):

```python
import tes

client = tes.HTTPClient("http://localhost:8000", token="poi_k7H2pQ…")
task_id = client.create_task(
    tes.Task(executors=[tes.Executor(image="alpine", command=["echo", "hi"])])
)
print(client.get_task(task_id).state)
```

`tes.HTTPClient(url, user="py-tes", password="poi_k7H2pQ…")` sends
Basic instead. Set either `token` or `user` and `password`, not both.

## Sprocket

[Sprocket](https://sprocket.bio) (St. Jude's WDL engine) has a TES
backend. Name it in `sprocket.toml` and give it the key as a bearer
token:

```toml
[run]
backend = "poiesis"

[run.backends.poiesis]
type = "tes"
url = "http://localhost:8000/ga4gh/tes/v1"
insecure = true          # needed for an http:// URL
inputs = "s3://poiesis-test/sprocket/inputs/"
outputs = "s3://poiesis-test/sprocket/outputs/"
cgroup_usage = false     # see below

[run.backends.poiesis.auth]
type = "bearer"
token = "poi_k7H2pQ…"

[run.storage.s3]
region = "us-east-1"
endpoint = "http://localhost:9000"

[run.storage.s3.auth]
access_key_id = "admin"
secret_access_key = "password"
```

Unlike Nextflow and Snakemake, Sprocket uses `url` as is, so it ends
in `/ga4gh/tes/v1` (with `/ga4gh/tes`, task creation gets `404`). For
Basic, use `type = "basic"`, any `username`, and the key as
`password`.

TaskPods don't share a file system with the host running Sprocket, so
`inputs` and `outputs` must be S3 URLs (ending in `/`), and
`[run.storage.s3]` must let Sprocket itself reach the same bucket:
it uploads local `File` inputs under `inputs` and reads each task's
`stdout`, `stderr` and output files from under `outputs`. `s3://`
`File` inputs are passed to Poiesis as they are.

Things that trip runs up:

- Sprocket declares `/mnt/task/stdout` and `/mnt/task/stderr` as the
  executor's `stdout` and `stderr` and as `FILE` outputs. Poiesis
  doesn't write the executor's output to those paths yet, so TOF
  fails and the task ends in `EXECUTOR_ERROR`. Until it does, start
  each `command` with
  `exec > /mnt/task/stdout 2> /mnt/task/stderr`.
- With `cgroup_usage` on (the default), Sprocket adds a task volume
  `/mnt/task/usage` and also lists it as a `DIRECTORY` output.
  Poiesis doesn't create volume directories, so the directory is
  missing and TOF fails. Set `cgroup_usage = false`.
- Sprocket runs commands with `bash` by default; for images without it
  (`alpine`), set `shell = "sh"` under `[run.task]`.

Sprocket sends `ignore_error: true` and reads the exit code from the
task log, so a task with a non-zero exit is `COMPLETE` in Poiesis and
failed in Sprocket.

Checked with Sprocket 0.34.1, bearer and Basic.

## Cromwell

Not tested end to end yet. One known incompatibility is handled:
Cromwell's TES backend tags every task with `workflow_id`,
`root_workflow_id` and `parent_workflow_id`, which is `null` for a
top-level workflow. TES tag values are strings, so Poiesis drops tags
whose value is `null` and accepts the task: the task keeps the other
two tags, and `parent_workflow_id` is simply absent, as if never sent
(in tag filters, sharing scopes and what the decision service sees
too). Any other value that is not a string (a number, an object) still
gets `422`.

## Other clients

Anything that can set a header works: send
`Authorization: Bearer poi_…` on every request, or HTTP Basic with the
key as password. A `401` with `invalid token` means the key is unknown,
revoked or expired; mint a new one. A `403` on create or cancel with
`API key lacks scope tasks:write` means a read-only key.

A client that logs in by itself (to mint a key, say) needn't be told
where: the `WWW-Authenticate` header of any `401` points to the
deployment's metadata, which lists its issuers; see
[Discovery](../concepts/authentication.md#discovery).
