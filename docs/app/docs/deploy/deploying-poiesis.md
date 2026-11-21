# Deploying Poiesis

This page walks through bringing Poiesis up on a local Kubernetes
cluster using the dev manifest. The Helm chart at
[`deployment/helm`](https://github.com/jaeaeich/poiesis/tree/main/deployment/helm)
generalises the same shape for production.

## What gets deployed

Two namespaces. `deps` holds the dependencies:

| Workload | Purpose |
| --- | --- |
| `postgres` | State store. One replica, PVC-backed. |
| `minio` | S3-compatible object store for TIF/TOF inputs/outputs. Dev only. |
| `keycloak` | OIDC identity provider with a ready-made `poiesis` realm. Dev only. |

`po` holds Poiesis:

| Workload | Purpose |
| --- | --- |
| `poiesis-migrate` | Job that applies the database migrations. |
| `poiesis-api` | TES API (FastAPI). |
| `poiesis-tctl` | Backstop reconciler, leader-elected via Leases. |

Three ServiceAccounts with namespace-scoped Roles:

- `poiesis-api` — create/delete Jobs and PVCs, read Pods.
- `poiesis-taskpod` — read Pods (used by TRec inside TaskPods).
- `poiesis-tctl` — watch Pods, CRU Leases.

## Steps

### 1. Build the images

```bash
git clone https://github.com/jaeaeich/poiesis.git
cd poiesis
docker build -f deployment/images/Dockerfile -t poiesis:dev .
docker build -f deployment/images/migrations.Dockerfile -t poiesis-migrations:dev .
```

OrbStack shares the host Docker daemon with the cluster, so the images
are immediately available. On minikube/kind, push them in:

```bash
# minikube
minikube image load poiesis:dev
minikube image load poiesis-migrations:dev
# kind
kind load docker-image poiesis:dev poiesis-migrations:dev
```

### 2. Apply the manifest

```bash
kubectl apply -f deployment/dev.yaml
kubectl -n deps wait --for=condition=Available deploy/keycloak --timeout=240s
kubectl -n po wait --for=condition=Available deploy/poiesis-api --timeout=240s
```

The API starts even if Keycloak isn't ready yet; until it has fetched
Keycloak's keys, authenticated requests get `503` with `Retry-After`.

`poiesis-migrate` is a Job, and a completed Job doesn't run again on
`apply`. After changing `./migrations/`, delete it first:
`kubectl -n po delete job poiesis-migrate`.

For a smoke test without an IdP, turn auth off:

```bash
kubectl -n po set env deploy/poiesis-api POIESIS_AUTH_ENABLED=false
```

See [Authentication](./authentication.md) for the production model.

### 3. Port-forward

```bash
kubectl -n po port-forward svc/poiesis-api 8000:8000 &
kubectl -n deps port-forward svc/keycloak 8080:8080 &
curl http://localhost:8000/ga4gh/tes/v1/service-info
```

### 4. Get a token

The `poiesis` realm comes with four users (the password is the
username) and two clients:

| User | Group |
| --- | --- |
| `alice`, `carol` | `lab-alpha` |
| `bob` | `lab-beta` |
| `admin` | `poiesis-admins` |

| Client | Use |
| --- | --- |
| `poiesis-cli` | Public. Authorization code + PKCE, device flow, and (dev only) password grant. |
| `poiesis-ci` | Confidential, client credentials. Secret `poiesis-ci-secret`. |

As a user:

```bash
TOKEN=$(curl -s http://localhost:8080/realms/poiesis/protocol/openid-connect/token \
  -d grant_type=password -d client_id=poiesis-cli -d scope=openid \
  -d username=alice -d password=alice | jq -r .access_token)
```

As a service account:

```bash
TOKEN=$(curl -s http://localhost:8080/realms/poiesis/protocol/openid-connect/token \
  -d grant_type=client_credentials -d scope=openid \
  -d client_id=poiesis-ci -d client_secret=poiesis-ci-secret | jq -r .access_token)
```

Check it works:

```bash
curl http://localhost:8000/ga4gh/tes/v1/tasks -H "Authorization: Bearer $TOKEN"
```

Tokens carry `aud: poiesis` and a `groups` claim, and live five
minutes. Keycloak pins their issuer to the in-cluster URL
(`http://keycloak.deps.svc:8080/realms/poiesis`), so tokens fetched
through the port-forward validate in the API too. Request
`scope=openid` if the API has [userinfo](./authentication.md) on:
Keycloak only answers userinfo for such tokens. User ids are fixed in
the realm, so `sub` (and with it task ownership) survives a Keycloak
restart.

For browser flows (authorization code, device flow) from the host,
make the pinned hostname resolve to the port-forward:

```bash
echo "127.0.0.1 keycloak.deps.svc" | sudo tee -a /etc/hosts
```

### 5. Mint an API key

Workflow engines need a credential that outlives a five-minute token:
an [API key](./api-keys.md). Mint one with the token from step 4:

```bash
KEY=$(curl -s -X POST http://localhost:8000/poiesis/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name": "dev", "ttl": "7d"}' | jq -r .key)
curl http://localhost:8000/ga4gh/tes/v1/tasks -H "Authorization: Bearer $KEY"
```

Or from the browser: the dev manifest sets up the Swagger UI login
with `poiesis-cli`. With the hosts entry above and both port-forwards
running, open <http://localhost:8000/docs>, click **Authorize**, log in
under `oidc` (authorization code) as `alice`, and run
`POST /poiesis/v1/api-keys`. The browser fetches Keycloak's discovery
document and login page from `keycloak.deps.svc:8080` itself, which is
why it needs the hosts entry. The realm accepts the Swagger UI on
`localhost:8000` and `localhost:18000` (for a port-forward to
`18000:8000` when 8000 is taken).

Use the key in your engine; see
[Workflow engines](../usage/workflow-engines.md).

## Submit a task

A no-IO echo task:

```bash
curl -X POST http://localhost:8000/ga4gh/tes/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "name": "hello",
    "executors": [
      {"image": "alpine:3.20", "command": ["echo", "hello from poiesis"]}
    ]
  }'
```

You'll get `{"id": "<uuid>"}`. Poll for state:

```bash
curl http://localhost:8000/ga4gh/tes/v1/tasks/<uuid> \
  -H "Authorization: Bearer $TOKEN"
```

A warm cluster reaches `COMPLETE` in under a minute. Cold image pulls
add to that.

## S3 inputs and outputs

Seed a test bucket once:

```bash
kubectl -n deps exec deploy/minio -- sh -c '
  mc alias set local http://localhost:9000 admin password &&
  mc mb -p local/poiesis-test &&
  echo "hello from s3" | mc pipe local/poiesis-test/input.txt
'
```

Submit a task that reads it, transforms, and writes back:

```bash
curl -X POST http://localhost:8000/ga4gh/tes/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "name": "s3-roundtrip",
    "inputs": [
      {"url": "s3://poiesis-test/input.txt", "path": "/data/in.txt", "type": "FILE"}
    ],
    "outputs": [
      {"url": "s3://poiesis-test/output.txt", "path": "/data/out.txt", "type": "FILE"}
    ],
    "executors": [
      {
        "image": "alpine:3.20",
        "command": ["sh", "-c",
                    "tr a-z A-Z < /transfer/data/in.txt > /transfer/data/out.txt"]
      }
    ]
  }'
```

Verify after `COMPLETE`:

```bash
kubectl -n deps exec deploy/minio -- sh -c '
  mc alias set local http://localhost:9000 admin password &&
  mc cat local/poiesis-test/output.txt
'
```

::: warning MinIO licensing
MinIO is AGPLv3 since 2024. The dev manifest bundles it for local
testing only. For production, point Poiesis at an external
S3-compatible endpoint (managed S3, Ceph, SeaweedFS, etc.) by setting
`S3_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and
`AWS_REGION` on the API Deployment.
:::

## Tear down

```bash
kubectl delete -f deployment/dev.yaml
```

## Production

The Helm chart at
[`deployment/helm`](https://github.com/jaeaeich/poiesis/tree/main/deployment/helm)
templates the same shape. Values cover:

- Image and pull policy
- Replicas and resource requests/limits per workload
- External Postgres DSN or chart-managed Postgres dependency
- S3 endpoint and credentials
- Ingress for the API
- TCtl HA replica count
- OIDC authentication ([dedicated page](./authentication.md))
- API keys and the Swagger UI login ([dedicated page](./api-keys.md))

`Chart.yaml` pins `kubeVersion: ">=1.29.0"` so installs fail fast on
incompatible clusters.
