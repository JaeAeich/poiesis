# Prerequisites

## Kubernetes 1.29+

Native sidecar containers (init containers with `restartPolicy: Always`)
are a 1.29 feature that the TaskPod requires.

- **Local:** [OrbStack](https://orbstack.dev/) (recommended on macOS),
  [Minikube](https://minikube.sigs.k8s.io/),
  [Kind](https://kind.sigs.k8s.io/), or [K3s](https://k3s.io/).
- **Production:** Managed K8s (GKE, EKS, AKS) at 1.29+. Default
  `StorageClass` with `ReadWriteOnce` PVC support. Egress to your
  S3/HTTP storage.

## PostgreSQL

Shared by the API, TRec, and TCtl. For dev, the in-cluster Postgres
in `dev.yaml` is fine. For production, managed Postgres or an HA
operator.

Migrations live under `./migrations/` and are applied by
[golang-migrate](https://github.com/golang-migrate/migrate) — the dev
manifest runs them via an init container.

## Helm (production)

Production deployments use the chart at
[`deployment/helm`](https://github.com/jaeaeich/poiesis/tree/main/deployment/helm).
For local exploration, `deployment/dev.yaml` applies directly with
`kubectl`.
