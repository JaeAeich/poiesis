#!/usr/bin/env bash
# Stand up Poiesis for the end-to-end tests on a kind cluster:
#   1. create the cluster (unless it exists),
#   2. build the API and migrations images from this checkout, load them,
#   3. deploy Postgres, the S3, GCS and Azure emulators and their Secrets
#      (deps.yaml),
#   4. make the S3 test buckets (one per S3 store), install the chart
#      (values.yaml). The tests make the GCS bucket and the Azure container
#      themselves.
# Then port-forward the API and run the tests:
#   kubectl --context kind-poiesis-e2e -n poiesis port-forward svc/poiesis-api 8000:8000 &
#   POIESIS_E2E_URL=http://localhost:8000 uv run pytest tests/e2e
# Delete the cluster afterwards: kind delete cluster --name poiesis-e2e
# Set SKIP_BUILD=1 to use poiesis:e2e and poiesis-migrations:e2e as they
# are, SKIP_CLUSTER=1 when
# the cluster is made elsewhere (CI).
set -euo pipefail

CLUSTER="${CLUSTER:-poiesis-e2e}"
NS=poiesis
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
kc=(kubectl --context "kind-$CLUSTER" -n "$NS")

if [[ -z "${SKIP_CLUSTER:-}" ]] && ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER" --wait 120s
fi

if [[ -z "${SKIP_BUILD:-}" ]]; then
  docker build -f "$root/deployment/images/Dockerfile" -t poiesis:e2e "$root"
  docker build -f "$root/deployment/images/migrations.Dockerfile" -t poiesis-migrations:e2e "$root"
fi
# Tag by image id, so that a rebuilt image rolls the release on upgrade.
tag_of() { docker image inspect -f '{{.Id}}' "$1:e2e" | cut -d: -f2 | cut -c1-12; }
api_tag="e2e-$(tag_of poiesis)"
migrations_tag="e2e-$(tag_of poiesis-migrations)"
docker tag poiesis:e2e "poiesis:$api_tag"
docker tag poiesis-migrations:e2e "poiesis-migrations:$migrations_tag"
kind load docker-image --name "$CLUSTER" "poiesis:$api_tag" "poiesis-migrations:$migrations_tag"

kubectl --context "kind-$CLUSTER" create namespace "$NS" --dry-run=client -o yaml \
  | kubectl --context "kind-$CLUSTER" apply -f -
"${kc[@]}" apply -f "$here/deps.yaml"
"${kc[@]}" rollout status deploy/postgres deploy/s3 deploy/gcs deploy/azurite --timeout=180s

# SeaweedFS doesn't create buckets on first write.
for bucket in poiesis-e2e poiesis-e2e-second; do
  for _ in $(seq 30); do
    "${kc[@]}" exec deploy/s3 -- sh -c \
      "echo 's3.bucket.create -name $bucket' | weed shell; echo s3.bucket.list | weed shell" \
      2>/dev/null | grep -q "^ *$bucket" && break
    sleep 2
  done
done

helm --kube-context "kind-$CLUSTER" upgrade --install poiesis "$root/deployment/helm/poiesis" \
  -n "$NS" -f "$here/values.yaml" --wait --timeout 5m \
  --set image.tag="$api_tag" --set migrations.image.tag="$migrations_tag"
