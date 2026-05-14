# Deploying Poiesis

This page walks through bringing Poiesis up on a local Kubernetes
cluster using the dev manifest. The Helm chart at
[`deployment/helm`](https://github.com/jaeaeich/poiesis/tree/main/deployment/helm)
generalises the same shape for production.

## What gets deployed

A single `poiesis` namespace containing:

| Workload | Purpose |
| --- | --- |
| `postgres` | State store. One replica, PVC-backed. |
| `poiesis-api` | TES API (FastAPI). Init containers wait for Postgres and run migrations. |
| `poiesis-tctl` | Backstop reconciler. 3 replicas, leader-elected via Leases. |
| `minio` | S3-compatible object store for TIF/TOF inputs/outputs. Dev only. |

Three ServiceAccounts with namespace-scoped Roles:

- `poiesis-api` — create/delete Jobs and PVCs, read Pods.
- `poiesis-taskpod` — read Pods (used by TRec inside TaskPods).
- `poiesis-tctl` — watch Pods, CRU Leases.

## Steps

### 1. Build the image

```bash
git clone https://github.com/jaeaeich/poiesis.git
cd poiesis
docker build -f deployment/images/Dockerfile -t poiesis:dev .
```

OrbStack shares the host Docker daemon with the cluster, so the image
is immediately available. On minikube/kind, push it in:

```bash
# minikube
minikube image load poiesis:dev
# kind
kind load docker-image poiesis:dev
```

### 2. Create the namespace and migrations ConfigMap

```bash
export KUBECONFIG=~/.kube/config

kubectl create namespace poiesis \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n poiesis create configmap poiesis-migrations \
  --from-file=./migrations \
  --dry-run=client -o yaml | kubectl apply -f -
```

Rerun the second command after any change under `./migrations/`.

### 3. Apply the manifest

```bash
kubectl apply -f deployment/dev.yaml
```

Wait until all four workloads report `Running`:

```bash
kubectl -n poiesis get pods
```

### 4. Port-forward and check the API

```bash
kubectl -n poiesis port-forward svc/poiesis-api 8000:8000
```

```bash
curl http://localhost:8000/ga4gh/tes/v1/service-info
```

## Submit a task

A no-IO echo task:

```bash
curl -X POST http://localhost:8000/ga4gh/tes/v1/tasks \
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
curl http://localhost:8000/ga4gh/tes/v1/tasks/<uuid>
```

A warm cluster reaches `COMPLETE` in under a minute. Cold image pulls
add to that.

## S3 inputs and outputs

Seed a test bucket once:

```bash
kubectl -n poiesis exec deploy/minio -- sh -c '
  mc alias set local http://localhost:9000 admin password &&
  mc mb -p local/poiesis-test &&
  echo "hello from s3" | mc pipe local/poiesis-test/input.txt
'
```

Submit a task that reads it, transforms, and writes back:

```bash
curl -X POST http://localhost:8000/ga4gh/tes/v1/tasks \
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
kubectl -n poiesis exec deploy/minio -- sh -c '
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
kubectl delete namespace poiesis
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

`Chart.yaml` pins `kubeVersion: ">=1.29.0"` so installs fail fast on
incompatible clusters.
