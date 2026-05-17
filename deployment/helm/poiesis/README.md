# Poiesis Helm chart

GA4GH TES (Task Execution Service) on Kubernetes. Single-Pod task
architecture, Postgres-backed, leader-elected backstop reconciler. This
chart deploys only the poiesis control plane — Postgres and (optional)
S3-compatible storage are operator-supplied.

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

Full schema in `values.schema.json`. The fields most deployments customise:

### Required

| Path | Type | Description |
|---|---|---|
| `database.existingSecret`         | string  | Name of a pre-existing Secret holding `DATABASE_URL`. |
| `taskpods.persistence.maxSizeGi`  | integer | Hard cap on `resources.disk_gb` from TES clients. API rejects oversized requests with HTTP 400 before any pod is created. |

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

- env: `DATABASE_URL`, anything starting with `AWS_` or `POIESIS_`.
- volumes: `task-data`, `postgres-ca`, `tmp`.

Total serialised JSON capped at ~32 KiB by Kubernetes' env-var size
limit. For typical extras this is plenty.

### Security

| Path | Type | Default | Description |
|---|---|---|---|
| `podSecurityEnforce` | string | `restricted` | PSS profile for poiesis-owned containers. `restricted` / `baseline` / `off`. Executors are exempt. |
| `imagePullSecrets`   | list   | `[]`         | Propagated to every chart component and every TaskPod. |
| `database.caConfigmap` | string | `""`       | ConfigMap (key `ca.crt`) mounted at `/etc/ssl/poiesis` for Postgres TLS. |

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
| `Job submission rejected: namespace quota exceeded` | Same as above, surfaced at submit time |

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
