# Poiesis Helm chart

GA4GH TES (Task Execution Service) on Kubernetes. Single-Pod task
architecture, Postgres-backed, leader-elected backstop reconciler. This
chart deploys only the poiesis control plane — Postgres and (optional)
object storage (S3 or S3-compatible, Google Cloud Storage, Azure Blob)
are operator-supplied.

## Quick start

```sh
# 1. Create the database Secret out-of-band. The chart never templates it.
kubectl -n poiesis create secret generic poiesis-db \
  --from-literal=DATABASE_URL='postgresql://user:pass@db.example.com/poiesis?sslmode=verify-full&sslrootcert=/etc/ssl/poiesis/ca.crt'

# 2. (Optional) Create the S3 credentials Secret.
kubectl -n poiesis create secret generic poiesis-s3 \
  --from-literal=AWS_ACCESS_KEY_ID=... \
  --from-literal=AWS_SECRET_ACCESS_KEY=...

# 3. Install.
helm install poiesis ./deployment/helm/poiesis \
  -n poiesis --create-namespace \
  --set database.existingSecret=poiesis-db \
  --set s3.existingSecret=poiesis-s3 \
  --set taskpods.persistence.maxSizeGi=500

# 4. Verify.
helm test poiesis -n poiesis
```

## Components

| Component       | Purpose                                                    |
|-----------------|------------------------------------------------------------|
| `api`           | TES HTTP endpoint. Stateless; horizontal-scalable.         |
| `tctl`          | Leader-elected controller. Sole writer of terminal state.  |
| Migration hook  | Runs `golang-migrate` pre-install/pre-upgrade.             |
| Per-task PVCs   | Scratch storage per TES task; GC'd via Job ownerReferences.|

Per-task TaskPods are created on-demand by the API in response to TES
`CreateTask` requests and live for the task's lifetime.

## Values reference

Full schema in `values.schema.json`; it refuses unknown keys, so a typo
such as `taskpod:` fails `helm lint` and `helm install`. The fields most
deployments customise:

### Required

| Path | Type | Description |
|---|---|---|
| `database.existingSecret`         | string  | Name of a pre-existing Secret holding `DATABASE_URL`. |
| `taskpods.persistence.maxSizeGi`  | integer | Hard cap on `resources.disk_gb` from TES clients. API rejects oversized requests with HTTP 400 before any pod is created. |

### Database pool (`database.pool`, `database.commandTimeoutSeconds`)

| Path | Type | Default | Description |
|---|---|---|---|
| `database.pool.minSize` | integer | `1` | Connections each API replica keeps open. |
| `database.pool.maxSize` | integer | `10` | Most connections each API replica opens. |
| `database.pool.acquireTimeoutSeconds` | integer | `10` | Seconds a request waits for a free connection; then it gets a 503 with `Retry-After`. |
| `database.commandTimeoutSeconds` | integer | `30` | Seconds a statement of the API or TCtl may run before it fails. Also bounds a hung connection. |

Postgres must allow API replicas × `maxSize` + 4 per TCtl replica + a few
for running tasks; see the production guide.

### TaskPod credentials (`taskpods.databaseSecret`, `taskpods.s3Secret`)

The API never writes `DATABASE_URL` or the S3 keys into a Job or Pod
spec. `trec`, `tif` and `tof` read them from Secrets by reference
(`secretKeyRef`); executors get none of them.

| Path | Type | Default | Description |
|---|---|---|---|
| `taskpods.databaseSecret` | string | `""` | Secret in the TaskPod namespace holding `DATABASE_URL` (key: `database.existingSecretKey`). Empty = `database.existingSecret`. |
| `taskpods.s3Secret`       | string | `""` | Secret in the TaskPod namespace holding `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and, optionally, `AWS_SESSION_TOKEN`. Empty = `s3.existingSecret`. |

A Pod can only read Secrets in its own namespace. When
`taskpods.namespace` differs from the release namespace, create both
Secrets there too. The chart does not copy them, and TaskPods cannot
start without them:

```sh
kubectl -n poiesis-tasks create secret generic poiesis-db \
  --from-literal=DATABASE_URL='postgresql://...'
kubectl -n poiesis-tasks create secret generic poiesis-s3 \
  --from-literal=AWS_ACCESS_KEY_ID=... \
  --from-literal=AWS_SECRET_ACCESS_KEY=...
```

### Object stores (`s3`, `gcs`, `azure`)

tif and tof stage inputs from and upload outputs to `s3://`, `gs://` and
`az://` URLs. A scheme is accepted at submit, and listed in service-info,
only when its provider is on. The end-to-end tests run all three on kind
against SeaweedFS (S3), fake-gcs-server (GCS) and Azurite (Azure); none
is run against the real cloud service in CI.

| Path | Type | Default | Description |
|---|---|---|---|
| `s3.enabled`              | bool   | `false` | Offer `s3://` without static keys (instance credentials). `s3.existingSecret` or `s3.roleArn` also turn S3 on. |
| `s3.endpoint`             | string | `""`    | `AWS_ENDPOINT_URL`; empty for AWS. An `http://` endpoint is allowed. |
| `s3.region`               | string | `""`    | `AWS_REGION`. |
| `s3.existingSecret`       | string | `""`    | Secret with `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and, optionally, `AWS_SESSION_TOKEN`. |
| `s3.roleArn`              | string | `""`    | IAM role tif/tof assume with a ServiceAccount token for `sts.amazonaws.com` (IRSA). The token is mounted into tif and tof only. |
| `s3.virtualHostedStyle`   | bool   | `false` | Virtual-hosted-style requests. `false` = path-style, which SeaweedFS and MinIO need. |
| `s3.serverSideEncryption` | string | `""`    | `AES256`, `aws:kms` or `aws:kms:dsse`. |
| `s3.kmsKeyId`             | string | `""`    | KMS key for `aws:kms` / `aws:kms:dsse`. |
| `s3.requesterPays`        | bool   | `false` | Pay for requests to requester-pays buckets. |
| `s3.anonymous`            | bool   | `false` | Unsigned requests, for public buckets; turns S3 on. No `existingSecret` or `roleArn` with it. |
| `gcs.enabled`             | bool   | `false` | Offer `gs://`. Needs `gcs.existingSecret` or `gcs.workloadIdentityProvider`, not both. |
| `gcs.existingSecret`      | string | `""`    | Secret in the TaskPod namespace with `GOOGLE_SERVICE_ACCOUNT_KEY` (a JSON key). |
| `gcs.workloadIdentityProvider` | string | `""` | Workload Identity Federation: full name of the pool provider (`//iam.googleapis.com/projects/<number>/locations/global/workloadIdentityPools/<pool>/providers/<provider>`). tif/tof get a ServiceAccount token for `https:<that name>` and trade it at Google STS. |
| `gcs.serviceAccount`      | string | `""`    | Service account to impersonate with the federated token. Empty: the federated principal is used directly. |
| `gcs.endpoint`            | string | `""`    | Base URL of the GCS API; empty for `https://storage.googleapis.com`. An `http://` endpoint is allowed. |
| `gcs.anonymous`           | bool   | `false` | Unsigned requests, for public buckets, in place of a key or `workloadIdentityProvider`. |
| `azure.enabled`           | bool   | `false` | Offer `az://container/blob`. Needs `azure.accountName`. |
| `azure.accountName`       | string | `""`    | Storage account. |
| `azure.existingSecret`    | string | `""`    | Secret in the TaskPod namespace with `AZURE_STORAGE_ACCOUNT_KEY` or `AZURE_STORAGE_SAS_TOKEN`. |
| `azure.clientId`, `azure.tenantId` | string | `""` | Workload identity: tif/tof get a ServiceAccount token for `api://AzureADTokenExchange`. Set both or neither. |
| `azure.endpoint`          | string | `""`    | Blob endpoint; empty for `https://<accountName>.blob.core.windows.net`. An `http://` endpoint is allowed. |
| `azure.anonymous`         | bool   | `false` | Unsigned requests, for public containers. No `existingSecret` or `clientId` with it. |
| `objectStores`            | list   | `[]`    | Named stores: `name`, `provider` (`s3`, `gcs`, `azure`), `buckets` (names and `prefix*` patterns), `anonymous`, and the provider's options above (without `enabled`). A URL goes to the store whose patterns match its bucket, else to the provider's default store. Overlapping patterns stop the API at startup. `existingSecret` is in the TaskPod namespace; keys reach tif/tof only. |

With `s3.roleArn`, `azure.clientId` or `gcs.workloadIdentityProvider`,
the API projects a ServiceAccount token for the provider into tif and tof
only, at `/var/run/secrets/poiesis/identity/<aws|azure|gcp>/token`.
Executors never get it: the TaskPod does not automount a token, and only
trec gets the Kubernetes API token. Do not annotate the TaskPod
ServiceAccount for the EKS or AKS webhooks (`eks.amazonaws.com/role-arn`,
`azure.workload.identity/client-id`) or for GKE Workload Identity
(`iam.gke.io/gcp-service-account`): they hand credentials to every
container, executors included. The trust policy (AWS), federated
credential (Azure) or pool provider's principal (Google) names the
subject `system:serviceaccount:<taskpod namespace>:<taskpod ServiceAccount>`.

### Storage (`taskpods.persistence`)

| Path | Type | Default | Description |
|---|---|---|---|
| `defaultSizeGi`      | integer        | `10`            | Size when a TES request omits `resources.disk_gb`. |
| `maxSizeGi`          | integer        | (required)      | Upper bound enforced at submit time. |
| `storageClass`       | string         | `""`            | `""` = cluster default. `"-"` = no provisioning (requires pre-bound PV). |
| `accessModes`        | list[string]   | `[ReadWriteOnce]` | RWO is sufficient for the single-Pod model; use `[ReadWriteMany]` on NFS/CephFS. |
| `labels`             | dict           | `{}`            | Merged onto every per-task PVC. |
| `annotations`        | dict           | `{}`            | Merged onto every per-task PVC. Use for Velero/Kasten backup selectors. |
| `retainAfterSeconds` | integer / null | `3600`          | `ttlSecondsAfterFinished` on the per-task Job. `null` → retained until manually deleted (audit). |

### Time limit (`taskpods.activeDeadlineSeconds`)

| Path | Type | Default | Description |
|---|---|---|---|
| `taskpods.activeDeadlineSeconds` | integer / null | `3600` | `activeDeadlineSeconds` on the per-task Job: how long a task may take, counted from the Job's creation. Kubernetes stops a task that runs longer and the task fails. Integer ≥ 1. `null` → no limit; a task whose Pod can't be scheduled then waits for as long as it takes, unless `tctl.unschedulableTimeoutSeconds` is set. |

### Outputs (`taskpods.outputGlobFallback`)

| Path | Type | Default | Description |
|---|---|---|---|
| `taskpods.outputGlobFallback` | boolean | `false` | When an output glob matches no file, TOF uploads nothing and logs a warning. `true` uploads every file under the output's `path_prefix` instead. |

### Local paths (`taskpods.fileUrlRoots`)

| Path | Type | Default | Description |
|---|---|---|---|
| `taskpods.fileUrlRoots` | list of strings | `[]` | Directories `file://` URLs may point into. Empty turns the scheme off. List only directories mounted into TaskPods through `extraVolumes` / `extraVolumeMounts`. |

### FTP (`taskpods.ftp`)

| Path | Type | Default | Description |
|---|---|---|---|
| `taskpods.ftp.enabled` | boolean | `true` | `ftp://` and `ftps://` inputs and outputs. A URL with no user logs in as anonymous; `user:password@` in a URL is stored with the task and left out of logs. `false` refuses both schemes with a 400 and drops them from service-info. |

### DRS (`taskpods.drs`)

| Path | Type | Default | Description |
|---|---|---|---|
| `taskpods.drs.enabled` | boolean | `false` | `drs://<host>/<object_id>` inputs. TIF resolves them through `https://<host>/ga4gh/drs/v1` and stages the access URL. |
| `taskpods.drs.allowedHosts` | list of strings | `[]` | DRS hosts tasks may name. Empty allows any host. |
| `taskpods.drs.existingSecret` | string | `""` | Secret in the TaskPod namespace with key `DRS_BEARER_TOKEN`, sent by TIF to DRS servers only (never to the data URL, never to executors). |

### Executor security (`taskpods.executorSecurityEnforce`)

| Path | Type | Default | Description |
|---|---|---|---|
| `taskpods.executorSecurityEnforce` | string | `"off"` | Profile of the executor containers and the TaskPod's Pod-level `securityContext`: `restricted` / `baseline` / `off`. `restricted` is needed in namespaces that enforce Pod Security `restricted`; every container then runs as uid 65532. Quote `"off"`. |
| `taskpods.podSecurityContext` | object | `{}` | Pod-level `securityContext` keys over the profile's, e.g. `{runAsUser: 1000, runAsGroup: 1000, fsGroup: 1000}`. |
| `taskpods.executorSecurityContext` | object | `{}` | `securityContext` keys of every executor container over the profile's. |

Rendered as `POIESIS_EXECUTOR_SECURITY_ENFORCE`,
`POIESIS_TASKPOD_POD_SECURITY_CONTEXT` and
`POIESIS_EXECUTOR_SECURITY_CONTEXT` (JSON); an unknown profile or key
stops the API at startup. On OpenShift keep `off`.

### System-container resources (`taskpods.systemResources`)

| Path | Type | Default | Description |
|---|---|---|---|
| `taskpods.systemResources.recorder` | resources | requests `10m`/`128Mi`, limits `200m`/`256Mi` | `trec` sidecar: watches the Pod, writes state and logs. |
| `taskpods.systemResources.filer` | resources | requests `100m`/`256Mi`, limits `1000m`/`1Gi` | `tif` and `tof`. Transfers stream (HTTP 8 KiB chunks, boto3 multipart), so memory doesn't grow with file size. |
| `taskpods.systemResources.ack` | resources | requests `10m`/`128Mi`, limits `100m`/`256Mi` | `ack`, the last container. |

Needed when the TaskPod namespace has a `ResourceQuota` on cpu or memory
and no `LimitRange`. Values merge with the defaults; `null` removes a
block. Rendered as JSON in `POIESIS_TASKPOD_{RECORDER,FILER,ACK}_RESOURCES`;
a malformed block or a request above its limit stops the API at startup.

### Executor resources and scheduling (`taskpods.resources` and others)

| Path | Type | Default | Description |
|---|---|---|---|
| `taskpods.resources.defaultCpuCores` | integer / null | `null` | CPU of each executor when the task sets no `cpu_cores`. `null`: no request or limit. |
| `taskpods.resources.defaultRamGb` | number / null | `null` | Memory (GiB) of each executor when the task sets no `ram_gb`. `null`: no request or limit. |
| `taskpods.resources.maxCpuCores` | integer / null | `null` | Largest `cpu_cores`; more is HTTP 400 at submit. |
| `taskpods.resources.maxRamGb` | number / null | `null` | Largest `ram_gb`; more is HTTP 400 at submit. |
| `taskpods.resources.cpuLimit` | bool | `true` | `false`: CPU request only, no CPU limit. |
| `taskpods.nodeSelector` | object | `{}` | `nodeSelector` of every TaskPod. |
| `taskpods.tolerations` | list | `[]` | Tolerations of every TaskPod. |
| `taskpods.affinity` | object | `{}` | Affinity of every TaskPod. A task's `zones` are added to each required node selector term. |
| `taskpods.priorityClassName` | string | `""` | PriorityClass of every TaskPod; a task's `priority_class` wins. |
| `taskpods.runtimeClassName` | string | `""` | RuntimeClass of every TaskPod. |
| `taskpods.preemptible` | `{nodeSelector, tolerations}` | empty | Added for `preemptible: true` tasks. Empty: `preemptible` is ignored. |
| `taskpods.gpu.resourceName` | string | `nvidia.com/gpu` | Resource `gpu_count` sets as a limit on each executor. |
| `taskpods.gpu.maxCount` | integer / null | `null` | Largest `gpu_count`; more is HTTP 400. |
| `taskpods.backendParameters.allowed` | list | `[]` | Keys honoured: `gpu_count`, `priority_class`, `node_pool`. Listed in `GET /service-info`. |
| `taskpods.backendParameters.priorityClasses` | list | `[]` | PriorityClasses `priority_class` may name. |
| `taskpods.backendParameters.nodePools` | object | `{}` | Name → `{nodeSelector, tolerations}` that `node_pool` may name. |

| TES `resources` field | TaskPod gets |
|---|---|
| `cpu_cores` | each executor: `requests.cpu`, and `limits.cpu` unless `cpuLimit: false` |
| `ram_gb` | each executor: `requests.memory` = `limits.memory`, as GiB |
| `zones` | required node affinity on `topology.kubernetes.io/zone` |
| `preemptible: true` | `taskpods.preemptible` node selector and tolerations |
| `backend_parameters.gpu_count` | each executor: `limits.<gpu.resourceName>` |
| `backend_parameters.priority_class` | `priorityClassName` |
| `backend_parameters.node_pool` | that pool's node selector and tolerations |

Executors are init containers that run one after another, so each gets
the full amount and the Pod is scheduled on the largest one (plus the
`trec` sidecar), not on the sum. An executor OOMKilled over its memory
limit ends the task `EXECUTOR_ERROR`. Keys not in `allowed`, and values
that can't be honoured, are ignored, or HTTP 400 under
`backend_parameters_strict`. Rendered as JSON in
`POIESIS_TASKPOD_SCHEDULING`; a bad value stops the API at startup.
TaskPods use the top-level `imagePullSecrets`.

### TaskPod extension points (`taskpods.extraEnv`, `taskpods.extraVolumes`, `taskpods.extraVolumeMounts`)

Operator-supplied env vars and volumes injected into every TaskPod. The
primary institutional use case is read-only reference data:

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

Scope:

- `extraEnv` → injects into poiesis-owned containers only (trec / tif /
  tof). Operator-supplied env on user-supplied executor images would be a
  surprising side-effect, so executors are excluded.
- `extraVolumes` → added to the TaskPod's `spec.volumes`.
- `extraVolumeMounts` → mounted in every container including executors.
  This is the load-bearing piece for reference-data use cases.

Reserved names rejected at API startup:

- env: `DATABASE_URL`, `DRS_BEARER_TOKEN`, anything starting with `AWS_` or `POIESIS_`.
- volumes: `task-data`, `postgres-ca`, `tmp`.

Total serialised JSON capped at ~32 KiB by Kubernetes' env-var size
limit. For typical extras this is plenty.

### Logs (`logLevel`, `logging.format`)

| Path | Type | Default | Description |
|---|---|---|---|
| `logLevel`       | string | `INFO` | Application log level. |
| `logging.format` | string | `json` | `json`: one JSON object per line on stderr. `text`: coloured lines, for a terminal. `""`: text when stderr is a terminal, else JSON. Applies to the API, TCtl and the TaskPod's `trec`, `tif` and `tof`; an unknown value stops them at startup. |

JSON lines have `timestamp`, `level`, `logger`, `message`, and
`request_id` (API) or `task_id` (`trec`, `tif`, `tof`, TCtl lines about
one task). The API also writes one `poiesis.access` line per request,
without query strings or headers. The audit log keeps its own format on
stdout.

### Metrics (`metrics`)

The API and tctl serve Prometheus metrics at `/metrics` on `metrics.port`,
apart from the TES API's port: not routed by the Ingress, no auth, not
in the access log. Labels are bounded (no task, user or owner labels).
The metrics, a dashboard and alert rules are in the docs' Monitoring
guide.

| Path | Type | Default | Description |
|---|---|---|---|
| `metrics.enabled` | bool | `true` | Serve `/metrics` and render the `<release>-api-metrics` and `<release>-tctl-metrics` Services. |
| `metrics.port` | integer | `9090` | Port of `/metrics` on the API and tctl Pods. |
| `metrics.scrapeAnnotations` | bool | `false` | `prometheus.io/scrape`, `/port`, `/path` annotations on the API and tctl Pods. |
| `metrics.service.annotations` | object | `{}` | Annotations of the metrics Services. |
| `metrics.serviceMonitor.enabled` | bool | `false` | Render a ServiceMonitor (needs the `monitoring.coreos.com` CRDs). |
| `metrics.serviceMonitor.labels` | object | `{}` | Labels your Prometheus selects ServiceMonitors by. |
| `metrics.serviceMonitor.interval`, `.scrapeTimeout` | string | `30s`, `10s` | Scrape timing. |
| `metrics.dashboard.enabled` | bool | `false` | Render a ConfigMap with `dashboards/poiesis.json` for the Grafana sidecar. |
| `metrics.dashboard.labels`, `.annotations` | object | `{grafana_dashboard: "1"}`, `{}` | Labels and annotations of that ConfigMap. |

### Service info (`serviceInfo`)

What `GET /service-info` says about this deployment. Empty keeps the
built-in value; invalid values stop the API from starting.

| Path | Env | Description |
|---|---|---|
| `id`                | `POIESIS_SERVICE_INFO_ID`                | Unique per deployment, e.g. `org.example.tes.prod`. Also the decision service's `context.tes.service_id`. Built-in: `org.ga4gh.poiesis`. |
| `name`              | `POIESIS_SERVICE_INFO_NAME`              | Human-readable name. |
| `description`       | `POIESIS_SERVICE_INFO_DESCRIPTION`       | Human-readable description. |
| `organization.name` | `POIESIS_SERVICE_INFO_ORGANIZATION_NAME` | Who runs the deployment. |
| `organization.url`  | `POIESIS_SERVICE_INFO_ORGANIZATION_URL`  | http(s) URL. |
| `contactUrl`        | `POIESIS_SERVICE_INFO_CONTACT_URL`       | http(s) or `mailto:` URL. |
| `documentationUrl`  | `POIESIS_SERVICE_INFO_DOCUMENTATION_URL` | http(s) URL. |
| `environment`       | `POIESIS_SERVICE_INFO_ENVIRONMENT`       | E.g. `prod`, `test`. Left out when empty. |
| `createdAt`         | `POIESIS_SERVICE_INFO_CREATED_AT`        | ISO 8601 with a UTC offset. Empty: the time of the request. |

`version` is the Poiesis version; the TES version is `type.version`.

### Security

| Path | Type | Default | Description |
|---|---|---|---|
| `podSecurityEnforce` | string | `restricted` | PSS profile for poiesis-owned containers. `restricted` / `baseline` / `off`. Executors follow `taskpods.executorSecurityEnforce`. |
| `imagePullSecrets`   | list   | `[]`         | Propagated to every chart component and every TaskPod. |
| `database.caConfigmap` | string | `""`       | ConfigMap (key `ca.crt`) mounted at `/etc/ssl/poiesis` for Postgres TLS. |

### NetworkPolicy (`networkPolicy`)

With `networkPolicy.enabled`, the API and tctl Pods may reach DNS, any
address on TCP 443 and 6443 (Kubernetes API, S3, issuers) and Postgres.
The API accepts traffic on 8000 from this release's Pods and the peers
below only; with metrics on, the API and tctl accept `metrics.port` from
`metricsFrom`. The migration hook and TaskPods are not selected.

| Path | Type | Default | Description |
|---|---|---|---|
| `networkPolicy.enabled` | bool | `false` | Render the API and tctl NetworkPolicies. |
| `networkPolicy.databaseEgress.port` | integer | `5432` | Postgres port the API and tctl may reach. |
| `networkPolicy.databaseEgress.to` | list | `[]` | NetworkPolicy peers (`ipBlock`, `namespaceSelector`, `podSelector`) where Postgres is. Empty: any address. `databaseEgress: null` drops the rule. |
| `networkPolicy.ingressFrom` | list | `[]` | Peers allowed to reach the API, e.g. a `namespaceSelector` for the ingress controller's namespace. |
| `networkPolicy.ingressFromPodSelector` | object | `{}` | Labels of further Pods in the release namespace allowed to reach the API. |
| `networkPolicy.metricsFrom` | list | `[]` | Peers allowed to reach `metrics.port` on the API and tctl. Empty: any address. |
| `networkPolicy.extraEgress` | list | `[]` | Extra egress rules, e.g. an issuer or S3 endpoint on another port. |

### Unschedulable timeout (`tctl.unschedulableTimeoutSeconds`)

| Path | Type | Default | Description |
|---|---|---|---|
| `tctl.unschedulableTimeoutSeconds` | integer / null | `null` | How long a task may wait for its Pod to be created and scheduled (ResourceQuota full, no node with room), counted from the Pod's (or, with no Pod yet, the Job's) creation. Past it, tctl ends the task as `SYSTEM_ERROR` with the scheduler's message (or, with no Pod, the Job's latest Warning event, such as a quota refusal) and deletes its Job. `null` → the task stays `QUEUED` until `taskpods.activeDeadlineSeconds` ends it. Integer ≥ 1. A Pod already bound to a node that doesn't start (image pull, volume mount) always fails after 5 minutes. |

### Rollout (`api.preStopSleepSeconds`, `api.terminationGracePeriodSeconds`, `api.topologySpreadConstraints`)

| Path | Type | Default | Description |
|---|---|---|---|
| `api.preStopSleepSeconds` | integer | `5` | preStop sleep before SIGTERM, so endpoints drop the Pod first. `0` → no hook. |
| `api.terminationGracePeriodSeconds` | integer | `40` | Gunicorn drains running requests for up to 30 s after SIGTERM; keep this ≥ `preStopSleepSeconds` + 30. |
| `api.topologySpreadConstraints` | list | `[]` | Pod topology spread. An entry without `labelSelector` gets the API Pods' selector labels. |
| `api.probes.{readiness,liveness}.failureThreshold` | integer | `3` | Probe failures before the Pod is marked unready / restarted. |

tctl has no PodDisruptionBudget: with the default one replica it would
block node drains, and an evicted tctl only delays task state updates
until a replica holds the lease again.

### TCtl liveness (`tctl.probes.liveness`)

| Path | Type | Default | Description |
|---|---|---|---|
| `tctl.probes.liveness.enabled` | bool | `true` | tctl touches `/tmp/poiesis-tctl-heartbeat` after each loop iteration, leader or standby; an exec probe fails when the file is missing or older than the limit below, and the kubelet restarts tctl. `/tmp` is the chart's writable `emptyDir`. |
| `tctl.probes.liveness.maxHeartbeatAgeSeconds` | integer | `600` | Age of the heartbeat at which the probe fails. Keep it above your longest pass. |
| `tctl.probes.liveness.periodSeconds`, `.timeoutSeconds`, `.failureThreshold` | integer | `30`, `5`, `3` | Probe timing. A hung tctl is restarted about `maxHeartbeatAgeSeconds + periodSeconds × failureThreshold` after its last iteration. |

### Component overrides (`api:`, `tctl:`)

Standard layered overrides: image, resources, probes, scheduling,
`extraEnv`, `extraEnvFrom`, `extraVolumes`, `extraVolumeMounts`,
`extraContainers`. Per-component values fall through to top-level
defaults when unset.

## Storage operator guide

### Choosing a StorageClass

Two decision axes:

1. **Performance tier.** Latency-sensitive workloads on local-attached
  SSDs (e.g., gp3, premium-ssd). Throughput-bound batch on standard.
2. **Encryption-at-rest and KMS.** Compliance-sensitive deployments
  (HIPAA, NHS) use a StorageClass with `encrypted: "true"` and a
  customer-managed KMS key.

Set `taskpods.persistence.storageClass` to the class name your cluster
admin has provisioned, or `"-"` for pre-bound PVs.

### Sizing

`defaultSizeGi` applies when TES clients don't set `disk_gb`. Typical:

- General bioinformatics: 10–50 GiB
- Genomics with inline reference data: 100–500 GiB
- Multi-sample joint calls: 500+ GiB

`maxSizeGi` is hard. Pair with a namespace `ResourceQuota` for
aggregate protection. Add ~10% overhead — filesystem journal/metadata
takes ~5%, tasks within that margin hit ENOSPC.

### ResourceQuota (strongly recommended)

The chart's `maxSizeGi` caps a single task. It does NOT cap aggregate
usage. Without a `ResourceQuota`, a client submitting many tasks at the
cap can saturate the cluster. Apply:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: poiesis-taskpods
  namespace: <taskpod namespace>
spec:
  hard:
    persistentvolumeclaims: "200"
    requests.storage: "10Ti"
```

When the quota is exceeded, the API returns HTTP 503 with `Retry-After:
30`, writes SYSTEM_ERROR for the task, and the operator sees the
classified reason in `system_logs`.

### Backup integration

Add the backup-operator annotation to
`taskpods.persistence.annotations`. Velero with `fs-backup`:

```yaml
taskpods:
  persistence:
    annotations:
      backup.velero.io/backup-volumes: task-data
```

### Audit retention

Set `taskpods.persistence.retainAfterSeconds: null` to omit
`ttlSecondsAfterFinished` from the Job entirely. The Job and PVC
survive until manually deleted. You are responsible for an
out-of-band cleanup process.

### Failure modes operators will see

| Symptom (system_logs) | What it means |
|---|---|
| `StorageClass not found` | Configured class doesn't exist on this cluster |
| `PVC unbound` | Provisioning failed (capacity, CSI driver down) |
| `Volume zone mismatch` | Scheduler can't find a node in the PV's AZ |
| `Quota exceeded` | Namespace `ResourceQuota` reached |
| `container exec-N OOMKilled: the executor exceeded its memory limit of …` | The task used more memory than its `ram_gb`; `EXECUTOR_ERROR` |
| `Job submission rejected: namespace quota exceeded` | Same as above, surfaced at submit time |
| `pending timeout: the Job created no Pod` | The Job had no Pod after 5 minutes: a `ResourceQuota` or an admission webhook rejects the Pod (see the Job's events) |
| `job failed without a pod: <reason>` | The Job failed and its Pod is gone: `DeadlineExceeded` when the time limit ran out, `BackoffLimitExceeded` when the Pod was deleted or lost with its node |

## What this chart does NOT do

By design, to keep the surface auditable:

- **Pre-bound PVs:** use `storageClass: "-"` and bind your own; chart
  will not template them.
- **Volume snapshots / clones:** not exposed.
- **Multiple storage tiers per TES request:** not exposed.
- **Embedded Postgres / MinIO:** external dependencies only.

For the reference-data use case (large shared read-only datasets like
genomes mounted into every task), use `taskpods.extraVolumes` +
`taskpods.extraVolumeMounts` as documented above.

## See also

- `values.yaml` — full default values with inline comments
- `values.schema.json` — JSON Schema validating chart inputs
- `templates/NOTES.txt` — post-install operator checklist
