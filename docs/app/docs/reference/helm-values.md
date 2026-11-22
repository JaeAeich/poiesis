---
description: Every key of the Poiesis Helm chart (deployment/helm/poiesis/values.yaml) with its default and what it does.
---

# Helm values

Every key of the chart at `deployment/helm/poiesis`, with its default.
The [Deploy](/deploy) page writes a `values.yaml` with only the keys you
change. `values.schema.json` validates values at `helm install` and
`helm lint`: an unknown key (a typo such as `taskpod:`) fails the install.

Defaults are layered: top-level keys apply to every component, and
`api:` and `tctl:` override only what differs. `taskpods:` shapes what
runs _for_ a task, not the control plane.

<Callout type="warn">

The chart never creates Secrets for credentials. Create the database
Secret (and the S3 Secret, unless you use workload identity) before installing; the
chart references them by name.

</Callout>

## Chart-wide

| Key                                              | Default            | What it does                                                                                                                                                                                       |
| ------------------------------------------------ | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nameOverride`, `fullnameOverride`               | `""`               | Name overrides; empty uses the release name.                                                                                                                                                       |
| `commonLabels`, `commonAnnotations`              | `{}`               | Added to every resource the chart renders.                                                                                                                                                         |
| `image.registry`                                 | `docker.io`        | Image registry, kept apart from the repository for policy engines.                                                                                                                                 |
| `image.repository`                               | `jaeaeich/poiesis` | Image repository.                                                                                                                                                                                  |
| `image.tag`                                      | `""`               | Empty uses the chart's `appVersion`.                                                                                                                                                               |
| `image.pullPolicy`                               | `IfNotPresent`     | Pull policy.                                                                                                                                                                                       |
| `imagePullSecrets`                               | `[]`               | Applied to the API, TCtl, the migration hook and every TaskPod.                                                                                                                                    |
| `podSecurityContext`, `containerSecurityContext` | `{}`               | Security contexts for the API, TCtl and the hook, merged over a profile derived from `podSecurityEnforce`.                                                                                         |
| `podSecurityEnforce`                             | `restricted`       | PodSecurity profile for Poiesis-owned containers (API, TCtl, hook, and `trec`/`tif`/`tof`/`ack`): `restricted`, `baseline` or `off`. Executors run user images and are exempt.                     |
| `nodeSelector`, `tolerations`, `affinity`        | `{}`, `[]`, `{}`   | Default scheduling; per-component values win.                                                                                                                                                      |
| `extraEnv`, `extraEnvFrom`                       | `[]`               | Extra environment for the API and TCtl; component extras append.                                                                                                                                   |
| `extraVolumes`, `extraVolumeMounts`              | `[]`               | Extra volumes for the API and TCtl; component extras append. Names must not collide.                                                                                                               |
| `extraManifests`                                 | `[]`               | Manifests rendered verbatim (strings or templates).                                                                                                                                                |
| `logLevel`                                       | `INFO`             | Application log level. The [audit log](./audit-log.md) ignores it.                                                                                                                                 |
| `logging.format`                                 | `json`             | Log line format of the API, TCtl, `trec`, `tif` and `tof`: `json`, `text` (coloured), or `""` (text on a terminal, else JSON). The audit log ignores it. See [Logs](../guides/production.md#logs). |

## Service accounts

| Key                              | Default | What it does                                                                                                                                                                                                                            |
| -------------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `serviceAccount.api.create`      | `true`  | Create the API's ServiceAccount; `false` with `name` binds an existing one (IRSA, Workload Identity).                                                                                                                                   |
| `serviceAccount.api.name`        | `""`    | Name of the ServiceAccount.                                                                                                                                                                                                             |
| `serviceAccount.api.annotations` | `{}`    | e.g. `eks.amazonaws.com/role-arn`.                                                                                                                                                                                                      |
| `serviceAccount.tctl.*`          | same    | The same for TCtl.                                                                                                                                                                                                                      |
| `serviceAccount.taskpod.*`       | same    | The same for TaskPods (used by `trec`, and by `tif` and `tof` for workload identity; executors don't get its tokens). Use `s3.roleArn`, `azure.clientId` or `gcs.workloadIdentityProvider` rather than cloud-identity annotations here. |

## Database

| Key                                   | Default        | What it does                                                                                                              |
| ------------------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `database.existingSecret`             | `""`           | Secret holding the full `DATABASE_URL`. Required.                                                                         |
| `database.existingSecretKey`          | `DATABASE_URL` | Key in that Secret.                                                                                                       |
| `database.caConfigmap`                | `""`           | ConfigMap with `ca.crt`, mounted read-only at `/etc/ssl/poiesis` in the API, TCtl and every TaskPod's Poiesis containers. |
| `database.pool.minSize`               | `1`            | Connections each API replica keeps open.                                                                                  |
| `database.pool.maxSize`               | `10`           | Most connections each API replica opens.                                                                                  |
| `database.pool.acquireTimeoutSeconds` | `10`           | Seconds a request waits for a free connection. Then it gets a 503 with `Retry-After: 1`.                                  |
| `database.commandTimeoutSeconds`      | `30`           | Seconds a database statement of the API or TCtl may run before it fails. Also bounds a connection that stopped answering. |

The URL has the form
`postgresql://USER:PASS@HOST:PORT/DB?sslmode=verify-full&sslrootcert=/etc/ssl/poiesis/ca.crt`.
To size the pool against Postgres, see
[Production: database](../guides/production.md#database).

## S3

| Key                       | Default | What it does                                                                                                                                           |
| ------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `s3.enabled`              | `false` | Offer `s3://` without keys or a role (instance credentials). `existingSecret` or `roleArn` also turn S3 on.                                            |
| `s3.endpoint`             | `""`    | `AWS_ENDPOINT_URL`; empty for AWS.                                                                                                                     |
| `s3.region`               | `""`    | `AWS_REGION`.                                                                                                                                          |
| `s3.existingSecret`       | `""`    | Secret with `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, and optionally `AWS_SESSION_TOKEN`; empty with workload identity or instance credentials. |
| `s3.roleArn`              | `""`    | IAM role `tif` and `tof` assume with a ServiceAccount token for `sts.amazonaws.com` (IRSA), mounted into them only.                                    |
| `s3.virtualHostedStyle`   | `false` | Virtual-hosted-style requests; `false` is path-style, which SeaweedFS and MinIO need.                                                                  |
| `s3.serverSideEncryption` | `""`    | `AES256`, `aws:kms` or `aws:kms:dsse` for uploads.                                                                                                     |
| `s3.kmsKeyId`             | `""`    | KMS key for `aws:kms` / `aws:kms:dsse`.                                                                                                                |
| `s3.requesterPays`        | `false` | Pay for requests to requester-pays buckets.                                                                                                            |

Needed only when inputs or outputs use `s3://`. While S3 is off, an
`s3://` URL is refused at submit. See
[Storage and staging](../concepts/storage.md#s3).

## gcs

| Key                            | Default | What it does                                                                                                                                                                                                                                                              |
| ------------------------------ | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gcs.enabled`                  | `false` | Offer `gs://`. Needs `gcs.existingSecret` or `gcs.workloadIdentityProvider`, not both.                                                                                                                                                                                    |
| `gcs.existingSecret`           | `""`    | Secret in the TaskPod namespace with `GOOGLE_SERVICE_ACCOUNT_KEY`, a service account's JSON key.                                                                                                                                                                          |
| `gcs.workloadIdentityProvider` | `""`    | Workload Identity Federation: full name of the pool provider, `//iam.googleapis.com/projects/<number>/locations/global/workloadIdentityPools/<pool>/providers/<provider>`. `tif` and `tof` get a ServiceAccount token for `https:<that name>` and trade it at Google STS. |
| `gcs.serviceAccount`           | `""`    | Service account to impersonate with the federated token. Needs `gcs.workloadIdentityProvider`. Empty uses the federated principal.                                                                                                                                        |
| `gcs.endpoint`                 | `""`    | Base URL of the GCS API; empty for `https://storage.googleapis.com`. `http://` is allowed.                                                                                                                                                                                |

## azure

| Key                                | Default | What it does                                                                                                                                                         |
| ---------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `azure.enabled`                    | `false` | Offer `az://container/blob`. Needs `azure.accountName`.                                                                                                              |
| `azure.accountName`                | `""`    | Storage account.                                                                                                                                                     |
| `azure.existingSecret`             | `""`    | Secret in the TaskPod namespace with `AZURE_STORAGE_ACCOUNT_KEY` or `AZURE_STORAGE_SAS_TOKEN`.                                                                       |
| `azure.clientId`, `azure.tenantId` | `""`    | Workload identity: the managed identity `tif` and `tof` act as, with a ServiceAccount token for `api://AzureADTokenExchange`. Set both or neither.                   |
| `azure.endpoint`                   | `""`    | Blob endpoint; empty for `https://<accountName>.blob.core.windows.net`. For a private endpoint, a sovereign cloud, Azure Stack Hub or Azurite. `http://` is allowed. |

CI runs `s3://`, `gs://` and `az://` end to end against emulators, not
the real clouds. See
[Storage and staging](../concepts/storage.md#object-stores).

## auth

Rendered as `POIESIS_AUTH_*` variables. See
[Authentication](../concepts/authentication.md).

| Key                        | Default  | What it does                                                                                                                              |
| -------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `auth.enabled`             | `true`   | With `true`, at least one issuer is required. `false` accepts every request as one anonymous owner (local dev, air-gapped single tenant). |
| `auth.issuers`             | `[]`     | Trusted issuers (`POIESIS_AUTH_ISSUERS`, JSON). Keys below.                                                                               |
| `auth.resource`            | `""`     | Public URL; enables RFC 9728 metadata and `resource_metadata` in every `401`. See [Discovery](../concepts/authentication.md#discovery).   |
| `auth.apiKeys.enabled`     | `false`  | Turn [API keys](../concepts/api-keys.md) on.                                                                                              |
| `auth.apiKeys.defaultTtl`  | `7d`     | Lifetime when the minting request names none (`<n>d` or `<n>h`).                                                                          |
| `auth.apiKeys.maxTtl`      | `90d`    | Longest lifetime a request may ask for.                                                                                                   |
| `auth.apiKeys.maxPerOwner` | `20`     | Active keys one owner may hold.                                                                                                           |
| `auth.swaggerUi.issuer`    | `""`     | One of `auth.issuers` (with discovery); empty turns the Swagger UI login off.                                                             |
| `auth.swaggerUi.clientId`  | `""`     | Public client allowing `<API URL>/docs/oauth2-redirect`.                                                                                  |
| `auth.swaggerUi.scopes`    | `openid` | Space-separated scopes requested.                                                                                                         |

### auth.issuers[]

| Key                     | Default    | What it does                                                                                                          |
| ----------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------- |
| `issuer`                | required   | Exact `iss` of the tokens and the discovery base URL.                                                                 |
| `audience`              | required   | Accepted `aud`: a string or a list.                                                                                   |
| `tokenTypes`            | `[at+jwt]` | Accepted header `typ` values, case-insensitive, `application/` optional. Keycloak: `[JWT]`. `[]` turns the check off. |
| `clients`               | any        | Accepted OAuth clients (`azp`, else `client_id`).                                                                     |
| `namespace`             | the issuer | Prefix of owner ids, `<namespace>\|<subject>`. No `\|`.                                                               |
| `principalClaim`        | `sub`      | Claim naming the subject; dotted paths walk nested objects.                                                           |
| `requiredScopes`        | none       | Scopes a token must carry, else `403`.                                                                                |
| `requiredClaim`         | none       | Admission rule `{name, values, prefixes}`; see [Claim rule](../concepts/authorization.md#claim-rule).                 |
| `admin`                 | none       | Built-in admin rule `{name, values, prefixes}`; ignored with a decision service.                                      |
| `actors`                | none       | Actors (`act.sub`) whose delegated tokens the built-in policy accepts.                                                |
| `userinfo.enabled`      | `false`    | Fetch userinfo per token (cached until expiry, at most 5 minutes). Not with `jwksUri`.                                |
| `jwksUri`               | discovery  | Static JWKS URL, for gateways that sign their own JWTs.                                                               |
| `jwksCacheTtl`          | `3600`     | Seconds to cache keys; unknown `kid`s refetch at most every 30 s.                                                     |
| `clockSkew`             | `30`       | Seconds of leeway on `exp`, `nbf`, `iat`.                                                                             |
| `timeout`               | `10`       | Seconds per call to the issuer.                                                                                       |
| `keyMinting.clients`    | none       | Clients whose tokens may mint API keys; without `keyMinting`, none may.                                               |
| `keyMinting.maxAuthAge` | none       | Also require a login at most this many seconds ago (`auth_time`).                                                     |

## authz

Rendered as `POIESIS_AUTHZ_*`. See [Authorization](../concepts/authorization.md).

| Key                                    | Default | What it does                                                                                             |
| -------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------- |
| `authz.decisionService.url`            | `""`    | OpenID AuthZEN 1.0 evaluation URL; empty keeps the built-in owner rule. Failures and timeouts are `503`. |
| `authz.decisionService.timeout`        | `2`     | Seconds per evaluation.                                                                                  |
| `authz.decisionService.claims`         | `[]`    | Claims sent in `subject.properties.claims`.                                                              |
| `authz.decisionService.credentialFile` | `""`    | Path (in the API pod) of a file with a bearer credential for the service.                                |
| `authz.sharing`                        | `false` | Let the decision service show tasks to others than their owner. Needs `decisionService.url`.             |
| `authz.maxOwners`                      | `1000`  | Most owners one list scope may name; more is `403`.                                                      |
| `authz.adminRead`                      | `false` | Built-in admins may list, get and cancel every task.                                                     |

The former global `authz.requiredClaim` is refused; set it per issuer.

## audit

| Key             | Default | What it does                                                                             |
| --------------- | ------- | ---------------------------------------------------------------------------------------- |
| `audit.enabled` | `true`  | One JSON line per decision and API key event on stdout. See [Audit log](./audit-log.md). |

## serviceInfo

Empty keeps the built-in value. Invalid values stop the API from
starting. See [Service info](../guides/production.md#service-info).

| Key                                           | Default | What it does                                                                                         |
| --------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------- |
| `serviceInfo.id`                              | `""`    | Unique id, reverse domain recommended; also `context.tes.service_id`. Built-in: `org.ga4gh.poiesis`. |
| `serviceInfo.name`, `serviceInfo.description` | `""`    | Human-readable name and description.                                                                 |
| `serviceInfo.organization.name`, `.url`       | `""`    | Who runs the deployment; `url` is http(s).                                                           |
| `serviceInfo.contactUrl`                      | `""`    | http(s) URL or `mailto:`.                                                                            |
| `serviceInfo.documentationUrl`                | `""`    | Docs for this deployment's users.                                                                    |
| `serviceInfo.environment`                     | `""`    | e.g. `prod`, `test`, `dev`, `staging`; left out when empty.                                          |
| `serviceInfo.createdAt`                       | `""`    | ISO 8601 with a UTC offset; empty is the time of the request.                                        |

## api

| Key                                                                                        | Default                                         | What it does                                                                                                                                        |
| ------------------------------------------------------------------------------------------ | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `api.replicas`                                                                             | `1`                                             | API replicas.                                                                                                                                       |
| `api.image`                                                                                | `{}`                                            | Image override (registry, repository, tag, pullPolicy), e.g. for canaries; TaskPods use the same image.                                             |
| `api.resources`                                                                            | requests `100m`/`256Mi`, limits `1000m`/`512Mi` | Container resources.                                                                                                                                |
| `api.probes.startup`                                                                       | enabled, every 2 s, 30 failures                 | Startup probe.                                                                                                                                      |
| `api.probes.readiness`                                                                     | enabled, every 5 s, timeout 2 s, 3 failures     | Readiness probe (`/readyz`): fails when Postgres doesn't answer `SELECT 1` within about 1.5 s. A pool with every connection in use counts as ready. |
| `api.probes.liveness`                                                                      | enabled, every 10 s, timeout 2 s, 3 failures    | Liveness probe.                                                                                                                                     |
| `api.preStopSleepSeconds`                                                                  | `5`                                             | Seconds the Pod sleeps in a preStop hook before SIGTERM, so Services and ingresses stop sending it requests first. `0` is no hook.                  |
| `api.terminationGracePeriodSeconds`                                                        | `40`                                            | Grace period. Gunicorn lets running requests finish for up to 30 s after SIGTERM; keep it at least `preStopSleepSeconds` + 30.                      |
| `api.topologySpreadConstraints`                                                            | `[]`                                            | Pod topology spread, e.g. across zones. An entry without `labelSelector` gets the API Pods' labels.                                                 |
| `api.service.type`, `.port`, `.annotations`                                                | `ClusterIP`, `8000`, `{}`                       | The API Service.                                                                                                                                    |
| `api.ingress.enabled`                                                                      | `false`                                         | Create an Ingress.                                                                                                                                  |
| `api.ingress.className`                                                                    | `""`                                            | Ingress class; empty for the cluster default.                                                                                                       |
| `api.ingress.annotations`                                                                  | `{}`                                            | e.g. `cert-manager.io/cluster-issuer`.                                                                                                              |
| `api.ingress.hosts`                                                                        | `poiesis.local`, path `/`                       | Hosts and paths.                                                                                                                                    |
| `api.ingress.tls`                                                                          | `[]`                                            | TLS entries `{secretName, hosts}`.                                                                                                                  |
| `api.pdb.enabled`, `.minAvailable`                                                         | `false`, `1`                                    | PodDisruptionBudget.                                                                                                                                |
| `api.autoscaling.*`                                                                        | off, 1–4 replicas, 70% CPU                      | HorizontalPodAutoscaler.                                                                                                                            |
| `api.extraEnv`, `.extraEnvFrom`, `.extraVolumes`, `.extraVolumeMounts`, `.extraContainers` | `[]`                                            | Appended to the chart-wide extras.                                                                                                                  |
| `api.podAnnotations`, `.podLabels`, `.nodeSelector`, `.tolerations`, `.affinity`           | empty                                           | Pod metadata and scheduling.                                                                                                                        |

## tctl

| Key                                                                                         | Default                                       | What it does                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tctl.replicas`                                                                             | `1`                                           | Leader election keeps one active; more give faster failover, not throughput. The chart renders no PodDisruptionBudget for TCtl: with one replica it would block node drains, and an evicted TCtl only delays task state updates. |
| `tctl.unschedulableTimeoutSeconds`                                                          | `null`                                        | Seconds a task may wait for its Pod to be created and scheduled before it ends `SYSTEM_ERROR`, at least 1. `null` waits until the [time limit](../concepts/tasks.md#time-limit).                                                 |
| `tctl.probes.liveness.enabled`                                                              | `true`                                        | Liveness probe: TCtl touches `/tmp/poiesis-tctl-heartbeat` after each loop iteration, and the probe fails when the file is missing or older than `maxHeartbeatAgeSeconds`.                                                       |
| `tctl.probes.liveness.maxHeartbeatAgeSeconds`                                               | `600`                                         | Heartbeat age at which the probe fails. Keep it above your longest pass.                                                                                                                                                         |
| `tctl.probes.liveness.periodSeconds`, `.timeoutSeconds`, `.failureThreshold`                | `30`, `5`, `3`                                | Probe timing.                                                                                                                                                                                                                    |
| `tctl.image`                                                                                | `{}`                                          | Image override.                                                                                                                                                                                                                  |
| `tctl.resources`                                                                            | requests `50m`/`128Mi`, limits `500m`/`256Mi` | Container resources.                                                                                                                                                                                                             |
| `tctl.extraEnv`, `.extraEnvFrom`, `.extraVolumes`, `.extraVolumeMounts`, `.extraContainers` | `[]`                                          | Appended to the chart-wide extras.                                                                                                                                                                                               |
| `tctl.podAnnotations`, `.podLabels`, `.nodeSelector`, `.tolerations`, `.affinity`           | empty                                         | Pod metadata and scheduling.                                                                                                                                                                                                     |

## taskpods

Baked into TaskPod manifests by the API when a task is created. See
[Task volumes](../concepts/task-volumes.md).

| Key                                                  | Default                                       | What it does                                                                                                                                                                                   |
| ---------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `taskpods.namespace`                                 | `""`                                          | Namespace for TaskPods; empty is the release namespace. When split, the chart renders the API and TaskPod Roles there.                                                                         |
| `taskpods.databaseSecret`                            | `""`                                          | Secret in the TaskPod namespace that `trec`, `tif` and `tof` read `DATABASE_URL` from, by reference. Empty is `database.existingSecret`. The key is `database.existingSecretKey`.              |
| `taskpods.s3Secret`                                  | `""`                                          | The same for the S3 keys. Empty is `s3.existingSecret`.                                                                                                                                        |
| `taskpods.persistence.defaultSizeGi`                 | `10`                                          | Volume size when a task omits `resources.disk_gb`.                                                                                                                                             |
| `taskpods.persistence.maxSizeGi`                     | `100`                                         | Largest `disk_gb`; more is `400`. Required by the schema.                                                                                                                                      |
| `taskpods.persistence.storageClass`                  | `""`                                          | `""` cluster default; `"-"` sets `storageClassName: ""`; else a named class.                                                                                                                   |
| `taskpods.persistence.accessModes`                   | `[ReadWriteOnce]`                             | Access modes; `[ReadWriteMany]` for RWX-only storage.                                                                                                                                          |
| `taskpods.persistence.labels`                        | `{}`                                          | Labels on every task volume.                                                                                                                                                                   |
| `taskpods.persistence.annotations`                   | `{}`                                          | Annotations on every task volume.                                                                                                                                                              |
| `taskpods.persistence.retainAfterSeconds`            | `3600`                                        | `ttlSecondsAfterFinished` of the Job; `null` keeps Job and volume.                                                                                                                             |
| `taskpods.activeDeadlineSeconds`                     | `3600`                                        | [Time limit](../concepts/tasks.md#time-limit) of a task in seconds (`activeDeadlineSeconds` of the Job), at least 1; `null` is no limit. Also ends the wait of a task that can't be scheduled. |
| `taskpods.outputGlobFallback`                        | `false`                                       | Upload everything under `path_prefix` when an output glob matches nothing.                                                                                                                     |
| `taskpods.fileUrlRoots`                              | `[]`                                          | Directories `file://` URLs may point into; empty turns the scheme off. See [Local paths](../concepts/storage.md#local-paths).                                                                  |
| `taskpods.ftp.enabled`                               | `true`                                        | `ftp://` and `ftps://` inputs and outputs; `false` refuses them with `400`. See [FTP](../concepts/storage.md#ftp).                                                                             |
| `taskpods.drs.enabled`                               | `false`                                       | `drs://` inputs. See [DRS](../concepts/storage.md#drs).                                                                                                                                        |
| `taskpods.drs.allowedHosts`                          | `[]`                                          | DRS hosts tasks may name; empty allows any host.                                                                                                                                               |
| `taskpods.drs.existingSecret`                        | `""`                                          | Secret in the TaskPod namespace with `DRS_BEARER_TOKEN`, sent by `tif` to DRS servers only.                                                                                                    |
| `taskpods.systemResources.recorder`                  | requests `10m`/`128Mi`, limits `200m`/`256Mi` | Resources of `trec`, the sidecar that records the task.                                                                                                                                        |
| `taskpods.systemResources.filer`                     | requests `100m`/`256Mi`, limits `1000m`/`1Gi` | Resources of `tif` and `tof`. Transfers are streamed, so memory doesn't grow with file size.                                                                                                   |
| `taskpods.systemResources.ack`                       | requests `10m`/`128Mi`, limits `100m`/`256Mi` | Resources of `ack`, the last container.                                                                                                                                                        |
| `taskpods.resources.defaultCpuCores`                 | `null`                                        | CPU cores of each executor when a task sets no `cpu_cores`; `null` is no request or limit. See [Resources and scheduling](../concepts/tasks.md#resources-and-scheduling).                      |
| `taskpods.resources.defaultRamGb`                    | `null`                                        | Memory (GiB) of each executor when a task sets no `ram_gb`; `null` is no request or limit.                                                                                                     |
| `taskpods.resources.maxCpuCores`                     | `null`                                        | Largest `cpu_cores`; more is `400`. `null` is no maximum.                                                                                                                                      |
| `taskpods.resources.maxRamGb`                        | `null`                                        | Largest `ram_gb`; more is `400`. `null` is no maximum.                                                                                                                                         |
| `taskpods.resources.cpuLimit`                        | `true`                                        | `false` sets CPU requests only, for clusters that avoid CPU limits. Memory always gets a limit.                                                                                                |
| `taskpods.nodeSelector`, `.tolerations`, `.affinity` | `{}`, `[]`, `{}`                              | Scheduling of every TaskPod (not the API or tctl). A task's `zones` are added to the required node affinity.                                                                                   |
| `taskpods.priorityClassName`                         | `""`                                          | PriorityClass of every TaskPod, unless the task picks one with `priority_class`.                                                                                                               |
| `taskpods.runtimeClassName`                          | `""`                                          | RuntimeClass of every TaskPod (e.g. gVisor, Kata).                                                                                                                                             |
| `taskpods.preemptible.nodeSelector`, `.tolerations`  | `{}`, `[]`                                    | Added for tasks with `preemptible: true`. Empty: `preemptible` is ignored.                                                                                                                     |
| `taskpods.gpu.resourceName`                          | `nvidia.com/gpu`                              | Resource a task's `gpu_count` sets as a limit on each executor.                                                                                                                                |
| `taskpods.gpu.maxCount`                              | `null`                                        | Largest `gpu_count`; more is `400`.                                                                                                                                                            |
| `taskpods.backendParameters.allowed`                 | `[]`                                          | `backend_parameters` keys honoured and listed in service-info: `gpu_count`, `priority_class`, `node_pool`. Others are ignored, or `400` with `backend_parameters_strict`.                      |
| `taskpods.backendParameters.priorityClasses`         | `[]`                                          | PriorityClasses a task may pick with `priority_class`. Needed to allow it.                                                                                                                     |
| `taskpods.backendParameters.nodePools`               | `{}`                                          | Name → `{nodeSelector, tolerations}` a task may pick with `node_pool`. Needed to allow it.                                                                                                     |
| `taskpods.extraEnv`                                  | `[]`                                          | Env for `trec`, `tif`, `tof`. Reserved: `DATABASE_URL`, `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_REGION`, `DRS_BEARER_TOKEN`, `POIESIS_*`.  |
| `taskpods.extraVolumes`                              | `[]`                                          | Volumes added to every TaskPod. Reserved names: `task-data`, `postgres-ca`, `tmp`.                                                                                                             |
| `taskpods.extraVolumeMounts`                         | `[]`                                          | Mounts for Poiesis containers and executors (reference data).                                                                                                                                  |

`taskpods.systemResources` entries are Kubernetes resources blocks
(`requests`, `limits`). Your values merge with the defaults key by key;
`null` (e.g. `ack: null`) leaves that container without requests or
limits. A malformed block, or a request above its limit, stops the API
at startup. Executors get their resources from the task, or from
`taskpods.resources` when it sets none. The scheduling values are checked
when the API starts: an unknown key, a default above its maximum, or an
allowed `priority_class` / `node_pool` with nothing to pick from stops it.

The image pull Secrets of TaskPods are the top-level `imagePullSecrets`.

The serialised TaskPod extras are capped at about 32 KiB (the
Kubernetes env-var limit); use a mounted ConfigMap for very large sets.

## networkPolicy

| Key                                    | Default | What it does                                                                                                                                                                                     |
| -------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `networkPolicy.enabled`                | `false` | Render NetworkPolicies for the API and TCtl. They may reach DNS, any address on TCP 443 and 6443, and Postgres; the API accepts traffic on 8000 from the release's own Pods and the peers below. |
| `networkPolicy.databaseEgress.port`    | `5432`  | Postgres port.                                                                                                                                                                                   |
| `networkPolicy.databaseEgress.to`      | `[]`    | NetworkPolicy peers where Postgres is (`ipBlock`, `namespaceSelector`, `podSelector`); empty is any address. `databaseEgress: null` drops the rule.                                              |
| `networkPolicy.ingressFrom`            | `[]`    | Peers allowed to reach the API, e.g. the ingress controller's namespace.                                                                                                                         |
| `networkPolicy.ingressFromPodSelector` | `{}`    | Labels of further Pods in the release namespace allowed to reach the API.                                                                                                                        |
| `networkPolicy.extraEgress`            | `[]`    | Extra egress rules for the API and TCtl, e.g. an issuer or S3 endpoint on another port.                                                                                                          |

## migrations

| Key                                   | Default                                      | What it does                               |
| ------------------------------------- | -------------------------------------------- | ------------------------------------------ |
| `migrations.image.registry`           | `docker.io`                                  | Migration image registry.                  |
| `migrations.image.repository`         | `jaeaeich/poiesis-migrations`                | golang-migrate image with the schema.      |
| `migrations.image.tag`, `.pullPolicy` | `""`, `IfNotPresent`                         | Tag (empty: `appVersion`) and pull policy. |
| `migrations.resources`                | requests `50m`/`64Mi`, limits `200m`/`128Mi` | Hook resources.                            |
