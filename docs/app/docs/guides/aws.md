---
description: Run Poiesis on Amazon EKS with S3 - IRSA for tif and tof only, or static keys in a Secret; minimal values and AWS-side steps.
---

# AWS (EKS)

Inputs and outputs on S3, from EKS. Pick one way for `tif` and `tof` to
get credentials. Executors get none of them.

The examples assume release `poiesis` in namespace `poiesis`, so the
TaskPod ServiceAccount is `poiesis-taskpod`. With `taskpods.namespace`
set, use that namespace instead.

## Workload identity (IRSA)

1. Create an IAM OIDC provider for the cluster:

   ```bash
   eksctl utils associate-iam-oidc-provider --cluster <cluster> --approve
   ```

2. Create a role with this trust policy (`<issuer>` is the cluster's OIDC
   issuer without `https://`):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": { "Federated": "arn:aws:iam::<account>:oidc-provider/<issuer>" },
         "Action": "sts:AssumeRoleWithWebIdentity",
         "Condition": {
           "StringEquals": {
             "<issuer>:sub": "system:serviceaccount:poiesis:poiesis-taskpod",
             "<issuer>:aud": "sts.amazonaws.com"
           }
         }
       }
     ]
   }
   ```

3. Allow the role `s3:GetObject`, `s3:PutObject` and `s3:ListBucket` on
   the buckets tasks use.

4. Install with:

   ```yaml
   s3:
     region: eu-central-1
     roleArn: arn:aws:iam::<account>:role/poiesis-filer
   ```

Don't add the `eks.amazonaws.com/role-arn` annotation to the TaskPod
ServiceAccount. The API mounts the token into `tif` and `tof` itself;
the webhook would put it in executors too.

## Static keys

```bash
kubectl -n poiesis create secret generic poiesis-s3 \
  --from-literal=AWS_ACCESS_KEY_ID=… \
  --from-literal=AWS_SECRET_ACCESS_KEY=…
```

```yaml
s3:
  region: eu-central-1
  existingSecret: poiesis-s3
```

## Public data next to a private bucket

Public datasets on AWS (the Registry of Open Data) take unsigned
requests. Add them as a named store, so the default store keeps your own
credentials:

```yaml
s3:
  region: eu-central-1
  roleArn: arn:aws:iam::<account>:role/poiesis-filer
objectStores:
  - name: open-data
    provider: s3
    buckets: ["1000genomes", "gnomad-public-*"]
    region: us-east-1 # the buckets' region
    anonymous: true
```

`s3://1000genomes/…` is then read without credentials; every other bucket
goes through the role. A named store can also be an on-prem Ceph or
MinIO with its own `endpoint` and `existingSecret`. See
[Several stores](../concepts/storage.md#several-stores).

## What is tested

CI runs `s3://` inputs and outputs end to end against SeaweedFS on kind,
with static keys, and one task that reads from the default store and
writes to a named store whose keys open only its bucket. IRSA is covered by unit tests only; it has not been run
on EKS in CI. Other S3 settings (encryption, requester pays, path or
virtual-hosted style) are in [Storage and staging](../concepts/storage.md#s3).
