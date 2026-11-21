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
  Secret holds `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.
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

## Storage

- Object storage reachable from the task namespace, with credentials
  in a Secret or through IRSA. See [Storage and staging](../concepts/storage.md).
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
  containers. Executors run user images and are exempt; constrain them
  with the namespace's PodSecurity admission level.
- `networkPolicy.enabled`, and restrict egress from the task
  namespace: `tof` and executors can reach whatever host a URL names.
- Rate-limit at the ingress or gateway: Poiesis doesn't.
- Split tasks into their own namespace with `taskpods.namespace` if
  you want them apart from the control plane.

Data-plane isolation (an input allowlist, per-task storage credentials, a
default TaskPod NetworkPolicy) is planned
([#126](https://github.com/jaeaeich/poiesis/issues/126)).

## Availability

- `api.replicas` above 1 and `api.pdb.enabled`, or `api.autoscaling`.
- `tctl.replicas` above 1 for faster failover (leader election means
  only one is active).

## Observability

- Ship the API's stdout to a log store: the
  [audit log](../reference/audit-log.md) lines are on it, and Poiesis keeps
  nothing.
- `logLevel: INFO` (`DEBUG` while setting up).

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
