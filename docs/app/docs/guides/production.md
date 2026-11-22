---
description: What to set before Poiesis serves real users - install, TLS and discovery, database, storage, identity, limits, security, observability and service info.
---

# Production checklist

The [Deploy](/deploy) page writes a `values.yaml` for the Helm chart.
This page is the list to go through before real users arrive. Every key
is described in [Helm values](../reference/helm-values.md).

<Callout type="info">

The chart isn't published to a registry yet
([#53](https://github.com/jaeaeich/poiesis/issues/53)). Install it from a
checkout: `helm install poiesis ./deployment/helm/poiesis -n poiesis -f values.yaml`.

</Callout>

## Install

- Kubernetes 1.29+. The chart pins `kubeVersion: ">=1.29.0-0"`.
- Create the Secrets first: the chart only references them, it never
  creates credentials. The database Secret holds `DATABASE_URL`; the S3
  Secret holds `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, plus
  `AWS_SESSION_TOKEN` for temporary credentials.
- TaskPods read the same Secrets by reference (`secretKeyRef`). No
  credential value is written into a Job or Pod spec.
- Pin `image.tag` (it defaults to the chart's `appVersion`).
- Migrations run as a Helm hook before the API starts; give the hook
  database access.

## Reachability and TLS

- Enable `api.ingress` with TLS, through cert-manager or an existing
  TLS Secret.
- Set `auth.resource` to the public URL, scheme included
  (`https://…`, even though Poiesis sees plain HTTP behind the ingress).
  Clients then discover your issuers from any `401`; see
  [Discovery](../concepts/authentication.md#discovery).
- With a path in the URL (`https://example.org/poiesis`), route
  `/.well-known/oauth-protected-resource/poiesis` to the API too.

## Database

- Managed Postgres or an HA operator.
- `sslmode=verify-full` with
  `sslrootcert=/etc/ssl/poiesis/ca.crt`, and the CA in a ConfigMap named by
  `database.caConfigmap` (key `ca.crt`).
- Size the connection pool against Postgres `max_connections`:
  - Each API replica opens up to `database.pool.maxSize` connections
    (default 10). Count the most replicas you run:
    `autoscaling.maxReplicas` when autoscaling is on, else `api.replicas`.
  - Each TCtl replica opens up to 4; the standby keeps 1 open.
  - Each running task opens a connection only while TRec writes an
    event (start, each executor's end) and while `tif` and `tof`
    start; it holds none in between. Thousands of tasks ending at once
    still open that many short connections.
  - Keep a few for the migration Job and for your own access.
  - Rule of thumb: `max_connections` ≥ API replicas × `maxSize` + 4 ×
    TCtl replicas + the tasks that start or end at the same moment + a
    few spare.
  - Put PgBouncer (transaction pooling) in front of Postgres when that
    sum is near `max_connections`, or when many tasks start and end
    together. Poiesis's database client (asyncpg) uses prepared
    statements, so use PgBouncer 1.21 or later with
    `max_prepared_statements` set.
  - A request waits at most `database.pool.acquireTimeoutSeconds` for a
    free connection, then gets a 503 with `Retry-After`. Raise `maxSize`
    if clients see that under normal load; add replicas if Postgres has
    room.
- `/readyz` fails only when Postgres doesn't answer. A replica whose
  pool is full stays ready: under a load that fills every pool, failing
  it would take all replicas out of the Service at once. Clients get
  503 with `Retry-After` instead. A pool stuck on a Postgres that
  stopped answering frees its connections after
  `database.commandTimeoutSeconds`; the probe fails from then on.
- `database.commandTimeoutSeconds` (default 30) bounds every statement
  of the API and TCtl, so a connection that stops answering fails the
  request or the TCtl pass instead of holding it.

## Storage

- Object storage reachable from the task namespace, with credentials
  in a Secret or through workload identity (`s3.roleArn` on EKS,
  `azure.clientId` on AKS, `gcs.workloadIdentityProvider` on GKE or any
  cluster). The token goes to `tif` and `tof` only; don't annotate the
  TaskPod ServiceAccount for the EKS or AKS webhooks or GKE Workload
  Identity, which would give credentials to executors too. See
  [Storage and staging](../concepts/storage.md#object-stores) and the
  [AWS](./aws.md), [Google Cloud](./gcp.md) and [Azure](./azure.md) guides.
- CI runs `s3://`, `gs://` and `az://` end to end against emulators
  (SeaweedFS, fake-gcs-server, Azurite), not against the real clouds. Try
  a task on your own bucket before you rely on it.
- `taskpods.persistence.maxSizeGi` set to the largest volume a task
  may ask for (the schema refuses an install without it).
- A StorageClass with `ReadWriteOnce` volumes, and
  `retainAfterSeconds` chosen for how long you keep finished tasks for
  debugging.
- Leave `taskpods.outputGlobFallback` off unless clients need it.
- Leave `taskpods.fileUrlRoots` empty unless tasks read shared data you
  mount into TaskPods; list only those mounts.
- `taskpods.activeDeadlineSeconds` set above your longest task. The
  default stops every task after one hour. See
  [Time limit](../concepts/tasks.md#time-limit).
- With a ResourceQuota on `cpu` or `memory` in the task namespace, every
  container needs requests and limits (or a LimitRange that sets them).
  The chart sets them on `trec`, `tif`, `tof` and `ack` through
  `taskpods.systemResources`. The containers run one after another
  next to `trec`, so with the defaults a TaskPod requests at least
  110m CPU and 384Mi memory (`trec` with `tif` or `tof`), plus `trec`'s
  share while executors run. Executors get theirs from the task's
  `cpu_cores` and `ram_gb`; set `taskpods.resources.defaultCpuCores`
  and `defaultRamGb` so tasks that ask for none get some too.
- `taskpods.resources.maxCpuCores` and `maxRamGb` set to what your
  largest node can give one Pod: a task asking for more gets a `400`
  instead of waiting forever for a node. If your cluster avoids CPU
  limits, set `cpuLimit: false`. See
  [Resources and scheduling](../concepts/tasks.md#resources-and-scheduling).
- TaskPods on dedicated nodes: `taskpods.nodeSelector` and
  `tolerations`; spot nodes for `preemptible: true` tasks:
  `taskpods.preemptible`; GPUs and node pools per task:
  `taskpods.backendParameters.allowed`.
- `tctl.unschedulableTimeoutSeconds` left `null` if tasks may queue for
  capacity (a full cluster, a ResourceQuota, an autoscaler adding
  nodes): they wait in `QUEUED` until the time limit. Set it to fail
  tasks that wait longer for a node.

## Identity

- At least one issuer, with an audience of its own per Poiesis
  instance and `tokenTypes` matching your IdP (Keycloak: `[JWT]`). See
  [Keycloak](./keycloak.md).
- `clients` set, so only your clients' tokens are accepted.
- A `requiredClaim` if only some of the issuer's users may use the
  service.
- `auth.apiKeys.enabled` only if engines need it, with
  `keyMinting.clients` limited to the client people log in with and a
  `maxTtl` you accept as the [deprovisioning lag](../concepts/api-keys.md#deprovisioning-lag).

## Restricted namespaces

A namespace that enforces Pod Security `restricted`
(`pod-security.kubernetes.io/enforce: restricted`) refuses a TaskPod
whose executors may run as root, keep their capabilities or escalate
privileges, so no task starts:

```text
pods "…" is forbidden: violates PodSecurity "restricted:latest": allowPrivilegeEscalation != false (container "exec-0" …
```

Set the executor profile to `restricted` there:

```yaml
taskpods:
  executorSecurityEnforce: restricted
```

Executors then get `allowPrivilegeEscalation: false`, `capabilities:
{drop: [ALL]}`, `runAsNonRoot: true` and seccomp `RuntimeDefault`, and
the Pod `runAsUser`, `runAsGroup` and `fsGroup` 65532 (the Poiesis
image's user) with `fsGroupChangePolicy: OnRootMismatch`. Every
container of the task runs as uid 65532 and shares the task volume.
What that means for task images:

- Images that need root at run time (package installs, `chown`,
  binding ports below 1024) fail.
- An image's own `USER` is replaced by 65532; `HOME` may point to a
  directory that user can't write. Tasks that need a writable home set
  `HOME` in the executor's `env`, e.g. to a path on the task volume.
- For another fixed user, set `taskpods.podSecurityContext`, e.g.
  `{runAsUser: 1000, runAsGroup: 1000, fsGroup: 1000}`.
  `taskpods.executorSecurityContext` does the same for the executor
  containers. Objects merge with the profile's key by key (e.g.
  `{capabilities: {add: [NET_BIND_SERVICE]}}` keeps `drop: [ALL]`);
  other values replace the profile's. Unknown keys and wrong value
  types stop the API at startup.

`restricted` executors need `podSecurityEnforce` `restricted` or
`baseline`: `trec`, `tif`, `tof` and `ack` must drop their capabilities
themselves, so with `off` the API refuses to start.

`baseline` only sets `allowPrivilegeEscalation: false`; executors keep
their user and capabilities, so root images still work. Namespaces that
enforce Pod Security `baseline` admit TaskPods with any of the three
profiles. On OpenShift keep `off`: its SecurityContextConstraints assign
users and seccomp profiles and may refuse fixed ones.

A namespace with a `ResourceQuota` on `limits.cpu` or `limits.memory`
and no `LimitRange` also needs limits on every container: set
`taskpods.resources.defaultCpuCores` and `defaultRamGb` for tasks that
ask for none (the defaults of `taskpods.systemResources` cover `trec`,
`tif`, `tof` and `ack`).

## Authorization

- Keep `authz.adminRead` off unless operators may see users' task
  data.
- With a decision service: secure transport (loopback sidecar, mesh
  mTLS or HTTPS), a NetworkPolicy so only Poiesis reaches it, and
  `sharing` only if tasks should be visible to others. See
  [Authorization](../concepts/authorization.md).

## Security

- Serve Poiesis over TLS only; API keys are bearer credentials.
- `podSecurityEnforce: restricted` (the default) for Poiesis-owned
  containers. Executors run user images and follow
  `taskpods.executorSecurityEnforce` (default `off`); see
  [Restricted namespaces](#restricted-namespaces).
- `networkPolicy.enabled`, and restrict egress from the task
  namespace: `tof` and executors can reach whatever host a URL names.
  The policies cover the API and TCtl. They allow DNS, TCP 443 and
  6443 to any address, and Postgres on `networkPolicy.databaseEgress.port`
  (default `5432`, to any address). Narrow Postgres with
  `databaseEgress.to`, and add an issuer or S3 endpoint on another port
  with `networkPolicy.extraEgress`.
- With an ingress controller in another namespace, allow it to reach
  the API:

  ```yaml
  networkPolicy:
    enabled: true
    ingressFrom:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: ingress-nginx
  ```

  The migration hook isn't selected by the policies; under a default-deny
  policy of your own, allow it to reach Postgres too.

- Rate-limit at the ingress or gateway: Poiesis doesn't.
- Split tasks into their own namespace with `taskpods.namespace` if
  you want them apart from the control plane. The API and TCtl stay in
  the release namespace, and so does TCtl's leader Lease; the chart
  renders their Roles for Jobs, PVCs and Pods in the task namespace.
  Create the database and S3 Secrets in that namespace too: TaskPods
  read them there, and the chart does not copy them. See
  [`taskpods.databaseSecret`](../reference/helm-values.md#taskpods).

Data-plane isolation (an input allowlist, per-task storage credentials, a
default TaskPod NetworkPolicy) is planned
([#126](https://github.com/jaeaeich/poiesis/issues/126)).

## Availability

- `api.replicas` above 1 and `api.pdb.enabled`, or `api.autoscaling`.
- `api.topologySpreadConstraints` to spread API replicas across zones
  or nodes.
- On rollouts the API sleeps `api.preStopSleepSeconds` (5 s) before
  SIGTERM, then gunicorn lets running requests finish for up to 30 s.
  Keep `api.terminationGracePeriodSeconds` (40 s) at least their sum.
- What the API does when the Kubernetes API server is slow or down:
  each call gives up after 30 seconds (5 to connect). CreateTask then
  answers 503 with `Retry-After`, ends the task as `SYSTEM_ERROR` with
  the reason in its system logs, and deletes its Job in case the create
  went through. No database connection is held while it waits.
- `tctl.replicas` above 1 for faster failover (leader election means
  only one is active). The chart has no TCtl PodDisruptionBudget: an
  evicted TCtl only delays task state updates until a replica holds the
  lease again.
- `tctl.probes.liveness` left on. TCtl touches a heartbeat file after
  each loop iteration; the probe restarts it when the file is older than
  `maxHeartbeatAgeSeconds` (10 minutes). Raise that if a pass can take
  longer, which needs thousands of tasks or a very slow API server.
- What TCtl does in an outage:
  - **API server down or slow**: each call times out (30 seconds at
    most). A pass that can't list every Job and Pod does nothing; a
    leader that can't renew its Lease within 20 seconds stops acting
    and stands down. Tasks stay as they are and are finalised once the
    API server answers again.
  - **Postgres down**: each pass fails when it reads the task rows, and
    does nothing. A terminal write that fails rolls back with its logs
    and is tried again on the next pass.
  - In both, TCtl keeps running and keeps touching its heartbeat, so it
    isn't restarted. Tasks that finish meanwhile are recorded when the
    outage ends, as long as their Job hasn't been removed after
    `retainAfterSeconds` ([#171](https://github.com/jaeaeich/poiesis/issues/171)).

## Observability

- Ship the API's stdout and stderr to a log store: the
  [audit log](../reference/audit-log.md) lines are on stdout, and Poiesis
  keeps nothing.
- `logLevel: INFO` (`DEBUG` while setting up).
- Scrape the API and TCtl metrics (`metrics.port`, `9090`, on by
  default; `metrics.serviceMonitor.enabled` for the Prometheus
  Operator) and add alerts for no TCtl leader, stalled reconcile passes,
  API 5xx and tasks queued too long. With `networkPolicy.enabled`, set
  `networkPolicy.metricsFrom` to your Prometheus. See
  [Monitoring](./monitoring.md).

### Logs

The API, TCtl and each TaskPod's `trec`, `tif` and `tof` write their log
to stderr, one JSON object per line (`logging.format: json`, the
default). `logging.format: text` gives coloured lines for reading in a
terminal; `""` picks text when stderr is a terminal and JSON otherwise.
The audit log keeps its own format on stdout.

Every line has `timestamp` (RFC 3339, UTC), `level`, `logger` and
`message`, and `exception` when there is one. API lines written while
serving a request have its `request_id`, the value returned in the
`X-Request-ID` response header and used in audit lines. `trec`, `tif`
and `tof` lines, and TCtl lines about one task, have its `task_id`.

The API writes one access line per request (logger `poiesis.access`):
`method`, `path`, `status`, `duration_ms`, `request_id` and, when the
request was authenticated, `owner`. Query strings, headers and bodies
are never logged. Probe requests (`/healthz`, `/readyz`, `/startupz`)
are logged at `DEBUG`.

Follow one request, from the request id a client got back:

```sh
kubectl -n poiesis logs deploy/poiesis-api \
  | jq -cR 'fromjson? | select(.request_id == "3f2c9a1e-…")'
```

Follow one task in TCtl and in its TaskPod:

```sh
kubectl -n poiesis logs deploy/poiesis-tctl \
  | jq -cR 'fromjson? | select(.task_id == "6d7e0c2a-…")'
# The TaskPod namespace (taskpods.namespace, default the release's):
kubectl -n poiesis logs job/task-6d7e0c2a-… --all-containers \
  | jq -cR 'fromjson? | select(.task_id)'
```

`fromjson?` skips lines that aren't JSON, such as the executors' output
or the API command's first line.

## Service info

`GET /service-info` tells registries and clients which deployment they
talk to. Give each deployment its own `id` and, ideally, an
`environment`:

```yaml
serviceInfo:
  id: org.example.tes.prod
  name: Example TES
  description: TES for the Example genomics platform
  organization:
    name: Example
    url: https://example.org
  contactUrl: mailto:tes@example.org
  documentationUrl: https://docs.example.org/tes
  environment: prod
  createdAt: 2026-01-15T09:00:00Z
```

Without the chart, set the same as `POIESIS_SERVICE_INFO_ID`, `_NAME`,
`_DESCRIPTION`, `_ORGANIZATION_NAME`, `_ORGANIZATION_URL`,
`_CONTACT_URL`, `_DOCUMENTATION_URL`, `_ENVIRONMENT` and `_CREATED_AT`.

- Unset values keep the built-in ones; `environment` is then left out and
  `createdAt` is the time of the request.
- URLs must be http(s); `contactUrl` may also be `mailto:`. `createdAt`
  is ISO 8601 with a UTC offset. Invalid values stop the API from
  starting.
- `id` is also sent to a decision service as `context.tes.service_id`
  ([Authorization](../concepts/authorization.md#request)).
- `version` is the Poiesis version; the TES version is `type.version`.

## Upgrading

- From `auth.oidc`: see
  [Migrating an existing deployment](../concepts/authentication.md#migrating-an-existing-deployment).
- Issuer hardening (token type, per-issuer claim rules): see
  [Upgrading to issuer hardening](../concepts/authentication.md#upgrading-to-issuer-hardening).
- From `tes-authzen/1`: see
  [Migrating from tes-authzen/1](../concepts/authorization.md#migrating-from-tes-authzen-1).
- Migration `000004` adds indexes on `tasks` for listing: owner with
  creation time, creation time with id, and a GIN index on `tags`. It
  builds them with plain `CREATE INDEX`, so writes to `tasks` (new
  tasks, state changes) wait until it finishes. On a large table, run
  the upgrade when few tasks are submitted.
