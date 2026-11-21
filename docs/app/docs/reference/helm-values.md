---
description: Every key of the Poiesis Helm chart (deployment/helm/poiesis/values.yaml) with its default and what it does.
---

# Helm values

Every key of the chart at `deployment/helm/poiesis`, with its default.
The [Deploy](/deploy) page writes a `values.yaml` with only the keys you
change. `values.schema.json` validates values at `helm install`.

Defaults are layered: top-level keys apply to every component, and
`api:` and `tctl:` override only what differs. `taskpods:` shapes what
runs *for* a task, not the control plane.

<Callout type="warn">

The chart never creates Secrets for credentials. Create the database
Secret (and the S3 Secret, unless you use IRSA) before installing; the
chart references them by name.

</Callout>

## Chart-wide

| Key | Default | What it does |
| --- | --- | --- |
| `nameOverride`, `fullnameOverride` | `""` | Name overrides; empty uses the release name. |
| `commonLabels`, `commonAnnotations` | `{}` | Added to every resource the chart renders. |
| `image.registry` | `docker.io` | Image registry, kept apart from the repository for policy engines. |
| `image.repository` | `jaeaeich/poiesis` | Image repository. |
| `image.tag` | `""` | Empty uses the chart's `appVersion`. |
| `image.pullPolicy` | `IfNotPresent` | Pull policy. |
| `imagePullSecrets` | `[]` | Applied to the API, TCtl, the migration hook and every TaskPod. |
| `podSecurityContext`, `containerSecurityContext` | `{}` | Security contexts for the API, TCtl and the hook, merged over a profile derived from `podSecurityEnforce`. |
| `podSecurityEnforce` | `restricted` | PodSecurity profile for Poiesis-owned containers (API, TCtl, hook, and `trec`/`tif`/`tof`/`ack`): `restricted`, `baseline` or `off`. Executors run user images and are exempt. |
| `nodeSelector`, `tolerations`, `affinity` | `{}`, `[]`, `{}` | Default scheduling; per-component values win. |
| `extraEnv`, `extraEnvFrom` | `[]` | Extra environment for the API and TCtl; component extras append. |
| `extraVolumes`, `extraVolumeMounts` | `[]` | Extra volumes for the API and TCtl; component extras append. Names must not collide. |
| `extraManifests` | `[]` | Manifests rendered verbatim (strings or templates). |
| `logLevel` | `INFO` | Application log level. The [audit log](./audit-log.md) ignores it. |

## Service accounts

| Key | Default | What it does |
| --- | --- | --- |
| `serviceAccount.api.create` | `true` | Create the API's ServiceAccount; `false` with `name` binds an existing one (IRSA, Workload Identity). |
| `serviceAccount.api.name` | `""` | Name of the ServiceAccount. |
| `serviceAccount.api.annotations` | `{}` | e.g. `eks.amazonaws.com/role-arn`. |
| `serviceAccount.tctl.*` | same | The same for TCtl. |
| `serviceAccount.taskpod.*` | same | The same for TaskPods (used by `trec`; executors don't get its token). |

## Database

| Key | Default | What it does |
| --- | --- | --- |
| `database.existingSecret` | `""` | Secret holding the full `DATABASE_URL`. Required. |
| `database.existingSecretKey` | `DATABASE_URL` | Key in that Secret. |
| `database.caConfigmap` | `""` | ConfigMap with `ca.crt`, mounted read-only at `/etc/ssl/poiesis` in the API, TCtl and every TaskPod's Poiesis containers. |

The URL has the form
`postgresql://USER:PASS@HOST:PORT/DB?sslmode=verify-full&sslrootcert=/etc/ssl/poiesis/ca.crt`.

## S3

| Key | Default | What it does |
| --- | --- | --- |
| `s3.endpoint` | `""` | `AWS_ENDPOINT_URL`; empty for AWS. |
| `s3.region` | `""` | `AWS_REGION`. |
| `s3.existingSecret` | `""` | Secret with `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`; empty with IRSA or IMDS credentials. |

Needed only when inputs or outputs use `s3://`. See
[Storage and staging](../concepts/storage.md).

## auth

Rendered as `POIESIS_AUTH_*` variables. See
[Authentication](../concepts/authentication.md).

| Key | Default | What it does |
| --- | --- | --- |
| `auth.enabled` | `true` | With `true`, at least one issuer is required. `false` accepts every request as one anonymous owner (local dev, air-gapped single tenant). |
| `auth.issuers` | `[]` | Trusted issuers (`POIESIS_AUTH_ISSUERS`, JSON). Keys below. |
| `auth.resource` | `""` | Public URL; enables RFC 9728 metadata and `resource_metadata` in every `401`. See [Discovery](../concepts/authentication.md#discovery). |
| `auth.apiKeys.enabled` | `false` | Turn [API keys](../concepts/api-keys.md) on. |
| `auth.apiKeys.defaultTtl` | `7d` | Lifetime when the minting request names none (`<n>d` or `<n>h`). |
| `auth.apiKeys.maxTtl` | `90d` | Longest lifetime a request may ask for. |
| `auth.apiKeys.maxPerOwner` | `20` | Active keys one owner may hold. |
| `auth.swaggerUi.issuer` | `""` | One of `auth.issuers` (with discovery); empty turns the Swagger UI login off. |
| `auth.swaggerUi.clientId` | `""` | Public client allowing `<API URL>/docs/oauth2-redirect`. |
| `auth.swaggerUi.scopes` | `openid` | Space-separated scopes requested. |

### auth.issuers[]

| Key | Default | What it does |
| --- | --- | --- |
| `issuer` | required | Exact `iss` of the tokens and the discovery base URL. |
| `audience` | required | Accepted `aud`: a string or a list. |
| `tokenTypes` | `[at+jwt]` | Accepted header `typ` values, case-insensitive, `application/` optional. Keycloak: `[JWT]`. `[]` turns the check off. |
| `clients` | any | Accepted OAuth clients (`azp`, else `client_id`). |
| `namespace` | the issuer | Prefix of owner ids, `<namespace>\|<subject>`. No `\|`. |
| `principalClaim` | `sub` | Claim naming the subject; dotted paths walk nested objects. |
| `requiredScopes` | none | Scopes a token must carry, else `403`. |
| `requiredClaim` | none | Admission rule `{name, values, prefixes}`; see [Claim rule](../concepts/authorization.md#claim-rule). |
| `admin` | none | Built-in admin rule `{name, values, prefixes}`; ignored with a decision service. |
| `actors` | none | Actors (`act.sub`) whose delegated tokens the built-in policy accepts. |
| `userinfo.enabled` | `false` | Fetch userinfo per token (cached until expiry, at most 5 minutes). Not with `jwksUri`. |
| `jwksUri` | discovery | Static JWKS URL, for gateways that sign their own JWTs. |
| `jwksCacheTtl` | `3600` | Seconds to cache keys; unknown `kid`s refetch at most every 30 s. |
| `clockSkew` | `30` | Seconds of leeway on `exp`, `nbf`, `iat`. |
| `timeout` | `10` | Seconds per call to the issuer. |
| `keyMinting.clients` | none | Clients whose tokens may mint API keys; without `keyMinting`, none may. |
| `keyMinting.maxAuthAge` | none | Also require a login at most this many seconds ago (`auth_time`). |

## authz

Rendered as `POIESIS_AUTHZ_*`. See [Authorization](../concepts/authorization.md).

| Key | Default | What it does |
| --- | --- | --- |
| `authz.decisionService.url` | `""` | OpenID AuthZEN 1.0 evaluation URL; empty keeps the built-in owner rule. Failures and timeouts are `503`. |
| `authz.decisionService.timeout` | `2` | Seconds per evaluation. |
| `authz.decisionService.claims` | `[]` | Claims sent in `subject.properties.claims`. |
| `authz.decisionService.credentialFile` | `""` | Path (in the API pod) of a file with a bearer credential for the service. |
| `authz.sharing` | `false` | Let the decision service show tasks to others than their owner. Needs `decisionService.url`. |
| `authz.maxOwners` | `1000` | Most owners one list scope may name; more is `403`. |
| `authz.adminRead` | `false` | Built-in admins may list, get and cancel every task. |

The former global `authz.requiredClaim` is refused; set it per issuer.

## audit

| Key | Default | What it does |
| --- | --- | --- |
| `audit.enabled` | `true` | One JSON line per decision and API key event on stdout. See [Audit log](./audit-log.md). |

## serviceInfo

Empty keeps the built-in value. Invalid values stop the API from
starting. See [Service info](../guides/production.md#service-info).

| Key | Default | What it does |
| --- | --- | --- |
| `serviceInfo.id` | `""` | Unique id, reverse domain recommended; also `context.tes.service_id`. Built-in: `org.ga4gh.poiesis`. |
| `serviceInfo.name`, `serviceInfo.description` | `""` | Human-readable name and description. |
| `serviceInfo.organization.name`, `.url` | `""` | Who runs the deployment; `url` is http(s). |
| `serviceInfo.contactUrl` | `""` | http(s) URL or `mailto:`. |
| `serviceInfo.documentationUrl` | `""` | Docs for this deployment's users. |
| `serviceInfo.environment` | `""` | e.g. `prod`, `test`, `dev`, `staging`; left out when empty. |
| `serviceInfo.createdAt` | `""` | ISO 8601 with a UTC offset; empty is the time of the request. |

## api

| Key | Default | What it does |
| --- | --- | --- |
| `api.replicas` | `1` | API replicas. |
| `api.image` | `{}` | Image override (registry, repository, tag, pullPolicy), e.g. for canaries; TaskPods use the same image. |
| `api.resources` | requests `100m`/`256Mi`, limits `1000m`/`512Mi` | Container resources. |
| `api.probes.startup` | enabled, every 2 s, 30 failures | Startup probe. |
| `api.probes.readiness` | enabled, every 5 s, timeout 2 s | Readiness probe. |
| `api.probes.liveness` | enabled, every 10 s, timeout 2 s | Liveness probe. |
| `api.service.type`, `.port`, `.annotations` | `ClusterIP`, `8000`, `{}` | The API Service. |
| `api.ingress.enabled` | `false` | Create an Ingress. |
| `api.ingress.className` | `""` | Ingress class; empty for the cluster default. |
| `api.ingress.annotations` | `{}` | e.g. `cert-manager.io/cluster-issuer`. |
| `api.ingress.hosts` | `poiesis.local`, path `/` | Hosts and paths. |
| `api.ingress.tls` | `[]` | TLS entries `{secretName, hosts}`. |
| `api.pdb.enabled`, `.minAvailable` | `false`, `1` | PodDisruptionBudget. |
| `api.autoscaling.*` | off, 1–4 replicas, 70% CPU | HorizontalPodAutoscaler. |
| `api.extraEnv`, `.extraEnvFrom`, `.extraVolumes`, `.extraVolumeMounts`, `.extraContainers` | `[]` | Appended to the chart-wide extras. |
| `api.podAnnotations`, `.podLabels`, `.nodeSelector`, `.tolerations`, `.affinity` | empty | Pod metadata and scheduling. |

## tctl

| Key | Default | What it does |
| --- | --- | --- |
| `tctl.replicas` | `1` | Leader election keeps one active; more give faster failover, not throughput. |
| `tctl.image` | `{}` | Image override. |
| `tctl.resources` | requests `50m`/`128Mi`, limits `500m`/`256Mi` | Container resources. |
| `tctl.extraEnv`, `.extraEnvFrom`, `.extraVolumes`, `.extraVolumeMounts`, `.extraContainers` | `[]` | Appended to the chart-wide extras. |
| `tctl.podAnnotations`, `.podLabels`, `.nodeSelector`, `.tolerations`, `.affinity` | empty | Pod metadata and scheduling. |

## taskpods

Baked into TaskPod manifests by the API when a task is created. See
[Task volumes](../concepts/task-volumes.md).

| Key | Default | What it does |
| --- | --- | --- |
| `taskpods.namespace` | `""` | Namespace for TaskPods; empty is the release namespace. When split, the chart renders the API and TaskPod Roles there. |
| `taskpods.persistence.defaultSizeGi` | `10` | Volume size when a task omits `resources.disk_gb`. |
| `taskpods.persistence.maxSizeGi` | `100` | Largest `disk_gb`; more is `400`. Required by the schema. |
| `taskpods.persistence.storageClass` | `""` | `""` cluster default; `"-"` sets `storageClassName: ""`; else a named class. |
| `taskpods.persistence.accessModes` | `[ReadWriteOnce]` | Access modes; `[ReadWriteMany]` for RWX-only storage. |
| `taskpods.persistence.labels` | `{}` | Labels on every task volume. |
| `taskpods.persistence.annotations` | `{}` | Annotations on every task volume. |
| `taskpods.persistence.retainAfterSeconds` | `3600` | `ttlSecondsAfterFinished` of the Job; `null` keeps Job and volume. |
| `taskpods.outputGlobFallback` | `false` | Upload everything under `path_prefix` when an output glob matches nothing. |
| `taskpods.extraEnv` | `[]` | Env for `trec`, `tif`, `tof`. Reserved: `DATABASE_URL`, `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `POIESIS_*`. |
| `taskpods.extraVolumes` | `[]` | Volumes added to every TaskPod. Reserved names: `task-data`, `postgres-ca`, `tmp`. |
| `taskpods.extraVolumeMounts` | `[]` | Mounts for Poiesis containers and executors (reference data). |

The serialised TaskPod extras are capped at about 32 KiB (the
Kubernetes env-var limit); use a mounted ConfigMap for very large sets.

## networkPolicy

| Key | Default | What it does |
| --- | --- | --- |
| `networkPolicy.enabled` | `false` | Render NetworkPolicies for the API and TCtl. |
| `networkPolicy.ingressFromPodSelector` | `{}` | Further pods (besides the release's own) allowed to reach the API. |
| `networkPolicy.extraEgress` | `[]` | Extra egress rules for the API and TCtl. |

## migrations

| Key | Default | What it does |
| --- | --- | --- |
| `migrations.image.registry` | `docker.io` | Migration image registry. |
| `migrations.image.repository` | `jaeaeich/poiesis-migrations` | golang-migrate image with the schema. |
| `migrations.image.tag`, `.pullPolicy` | `""`, `IfNotPresent` | Tag (empty: `appVersion`) and pull policy. |
| `migrations.resources` | requests `50m`/`64Mi`, limits `200m`/`128Mi` | Hook resources. |
