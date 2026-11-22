---
description: Run Poiesis on Google Kubernetes Engine with Cloud Storage - Workload Identity Federation for tif and tof only, or a service account key; minimal values and Google Cloud steps.
---

# Google Cloud (GKE)

Inputs and outputs on Cloud Storage, from GKE (or any cluster with a
public OIDC issuer). Pick one way for `tif` and `tof` to get credentials.
Executors get none of them.

The examples assume release `poiesis` in namespace `poiesis`, so the
TaskPod ServiceAccount is `poiesis-taskpod`, and project `my-project`
with number `123456789`.

## Workload Identity Federation

Poiesis does not use GKE's built-in Workload Identity
(`iam.gke.io/gcp-service-account`): its metadata server answers every
container of the Pod, executors included. Instead `tif` and `tof` trade a
ServiceAccount token, mounted into them only, at Google STS. That needs a
workload identity pool provider that trusts the cluster's issuer.

1. Create a pool and an OIDC provider for the cluster's issuer:

   ```bash
   ISSUER=$(kubectl get --raw /.well-known/openid-configuration | jq -r .issuer)
   gcloud iam workload-identity-pools create poiesis --location=global
   gcloud iam workload-identity-pools providers create-oidc cluster \
     --location=global --workload-identity-pool=poiesis \
     --issuer-uri="$ISSUER" \
     --attribute-mapping=google.subject=assertion.sub
   ```

   On GKE the issuer is
   `https://container.googleapis.com/v1/projects/my-project/locations/<location>/clusters/<cluster>`.
   Leave `--allowed-audiences` unset: the token's audience is then
   accepted.

2. Let the TaskPod ServiceAccount act as a service account with bucket
   access:

   ```bash
   gcloud iam service-accounts create poiesis-filer
   gcloud storage buckets add-iam-policy-binding gs://<bucket> \
     --member=serviceAccount:poiesis-filer@my-project.iam.gserviceaccount.com \
     --role=roles/storage.objectUser
   gcloud iam service-accounts add-iam-policy-binding \
     poiesis-filer@my-project.iam.gserviceaccount.com \
     --role=roles/iam.workloadIdentityUser \
     --member="principal://iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/poiesis/subject/system:serviceaccount:poiesis:poiesis-taskpod"
   ```

   Or skip the service account: grant `roles/storage.objectUser` on the
   bucket to that `principal://…` member and leave `gcs.serviceAccount`
   empty.

3. Install with:

   ```yaml
   gcs:
     enabled: true
     workloadIdentityProvider: //iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/poiesis/providers/cluster
     serviceAccount: poiesis-filer@my-project.iam.gserviceaccount.com
   ```

Executors can still reach the node's metadata server, as any Pod on the
node can. What it answers them depends on the node pool, not on Poiesis;
the filers' credentials never come from it.

## Service account key

```bash
gcloud iam service-accounts keys create key.json \
  --iam-account=poiesis-filer@my-project.iam.gserviceaccount.com
kubectl -n poiesis create secret generic poiesis-gcs \
  --from-file=GOOGLE_SERVICE_ACCOUNT_KEY=key.json
```

```yaml
gcs:
  enabled: true
  existingSecret: poiesis-gcs
```

## What is tested

CI runs `gs://` inputs and outputs end to end against fake-gcs-server on
kind, with `gcs.endpoint` and an unsigned key. Uploads in parts (files
over 8 MiB) are not covered there: the emulator lacks them. Workload
Identity Federation is covered by unit tests against a mocked STS and
IAM Credentials API; it has not been run on GKE in CI. More in
[Storage and staging](../concepts/storage.md#google-cloud-storage).
