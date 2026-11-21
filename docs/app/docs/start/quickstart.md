---
description: Run Poiesis on a local Kubernetes cluster with the dev manifest, get a token, mint an API key and submit tasks.
---

# Quickstart

Bring Poiesis up on a local cluster with the dev manifest
(`deployment/dev.yaml`), then submit a task. It takes about ten minutes.
For a real cluster, use [Deploy](/deploy) and the
[Production checklist](../guides/production.md).

You need Kubernetes 1.29+ (OrbStack, minikube, kind or k3s), `kubectl`,
Docker, `curl` and `jq`.

## What gets deployed

Two namespaces. `deps` holds the dependencies:

| Workload | Purpose |
| --- | --- |
| `postgres` | State store. One replica, PVC-backed. |
| `s3` | [SeaweedFS](https://github.com/seaweedfs/seaweedfs), an S3-compatible store for inputs and outputs. Dev only. |
| `keycloak` | OIDC identity provider with a ready-made `poiesis` realm. Dev only. |

`po` holds Poiesis:

| Workload | Purpose |
| --- | --- |
| `poiesis-migrate` | Job that applies the database migrations. |
| `poiesis-api` | TES API (FastAPI). |
| `poiesis-tctl` | Backstop reconciler, leader-elected via Leases. |

Three ServiceAccounts with namespace-scoped Roles:

- `poiesis-api`: create and delete Jobs, create PVCs, read Pods and Pod
  logs. Kubernetes deletes each PVC with its Job.
- `poiesis-taskpod`: read Pods and Pod logs. Used by TRec inside
  TaskPods; executors don't get its token.
- `poiesis-tctl`: watch Pods, read Pod logs, create, read and update
  Leases.

## 1. Build the images

```bash
git clone https://github.com/jaeaeich/poiesis.git
cd poiesis
docker build -f deployment/images/Dockerfile -t poiesis:dev .
docker build -f deployment/images/migrations.Dockerfile -t poiesis-migrations:dev .
```

OrbStack shares the host Docker daemon with the cluster, so the images
are available right away. On minikube or kind, load them:

```bash
# minikube
minikube image load poiesis:dev
minikube image load poiesis-migrations:dev
# kind
kind load docker-image poiesis:dev poiesis-migrations:dev
```

## 2. Apply the manifest

```bash
kubectl apply -f deployment/dev.yaml
kubectl -n deps wait --for=condition=Available deploy/keycloak --timeout=240s
kubectl -n po wait --for=condition=Available deploy/poiesis-api --timeout=240s
```

The API starts even if Keycloak isn't ready yet. Until it has fetched
Keycloak's keys, authenticated requests get `503` with `Retry-After`.

<Callout type="info">

`poiesis-migrate` is a Job, and a completed Job doesn't run again on
`apply`. After changing `./migrations/`, delete it first:
`kubectl -n po delete job poiesis-migrate`.

</Callout>

For a smoke test without an identity provider, turn auth off:

```bash
kubectl -n po set env deploy/poiesis-api POIESIS_AUTH_ENABLED=false
```

## 3. Port-forward

```bash
kubectl -n po port-forward svc/poiesis-api 8000:8000 &
kubectl -n deps port-forward svc/keycloak 8080:8080 &
curl http://localhost:8000/ga4gh/tes/v1/service-info
# where to log in (RFC 9728)
curl http://localhost:8000/.well-known/oauth-protected-resource
```

## 4. Get a token

The `poiesis` realm has four users (the password is the user name):

| User | Group |
| --- | --- |
| `alice`, `carol` | `lab-alpha` |
| `bob` | `lab-beta` |
| `admin` | `poiesis-admins` |

`admin` is the issuer's built-in [admin](../concepts/authorization.md#admin):
it may list and revoke anyone's API keys, but sees only its own tasks,
since `adminRead` is off. The realm and its two clients are described in
the [Keycloak guide](../guides/keycloak.md#the-dev-realm).

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

Tokens live five minutes.

## 5. Mint an API key

Workflow engines need a credential that outlives a five-minute token: an
[API key](../concepts/api-keys.md). Mint one with the token:

```bash
KEY=$(curl -s -X POST http://localhost:8000/poiesis/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name": "dev", "ttl": "7d"}' | jq -r .key)
curl http://localhost:8000/ga4gh/tes/v1/tasks -H "Authorization: Bearer $KEY"
```

You can also mint one in the browser from the Swagger UI; see the
[Keycloak guide](../guides/keycloak.md#browser-logins-against-the-dev-realm).
Use the key in your engine: [Workflow engines](../guides/workflow-engines.md).

## Submit a task

A task without inputs or outputs:

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

You get `{"id": "<uuid>"}`. Poll for its state:

```bash
curl http://localhost:8000/ga4gh/tes/v1/tasks/<uuid> \
  -H "Authorization: Bearer $TOKEN"
```

A warm cluster reaches `COMPLETE` in under a minute. Cold image pulls add
to that.

## S3 inputs and outputs

The dev store is SeaweedFS: S3 at `http://s3.deps.svc.cluster.local:9000`,
access key `admin`, secret `password`. It doesn't create buckets on first
write. Seed a test bucket once, from inside the pod (`weed shell` makes
the bucket, the filer on port 8888 takes the file):

```bash
kubectl -n deps exec deploy/s3 -- sh -c '
  echo "s3.bucket.create -name poiesis-test" | weed shell &&
  echo "hello from s3" | curl -sf -T - http://localhost:8888/buckets/poiesis-test/input.txt
'
```

Or from the host with any S3 client, through
`kubectl -n deps port-forward svc/s3 9000:9000`:

```bash
export AWS_ACCESS_KEY_ID=admin AWS_SECRET_ACCESS_KEY=password AWS_REGION=us-east-1
export AWS_ENDPOINT_URL=http://localhost:9000
aws s3 mb s3://poiesis-test
echo "hello from s3" | aws s3 cp - s3://poiesis-test/input.txt
```

Submit a task that reads it, transforms it and writes it back:

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
                    "tr a-z A-Z < /data/in.txt > /data/out.txt"]
      }
    ]
  }'
```

Check after `COMPLETE`:

```bash
kubectl -n deps exec deploy/s3 -- \
  curl -s http://localhost:8888/buckets/poiesis-test/output.txt
```

<Callout type="warn">

Clusters set up before the switch from MinIO still have its Deployment,
Service and volume. Remove them, re-apply, and restart Poiesis so it
picks up the new endpoint:

```bash
kubectl -n deps delete deploy/minio svc/minio pvc/minio
kubectl apply -f deployment/dev.yaml
kubectl -n po rollout restart deploy/poiesis-api deploy/poiesis-tctl
```

</Callout>

## Tear down

```bash
kubectl delete -f deployment/dev.yaml
```

## Next

- How a task runs: [Tasks and TaskPods](../concepts/tasks.md)
- Run a workflow: [Workflow engines](../guides/workflow-engines.md)
- Put it in production: [Deploy](/deploy) and the
  [Production checklist](../guides/production.md)
