---
description: Run Poiesis on Azure Kubernetes Service with Blob Storage - workload identity for tif and tof only, or an account key or SAS token; minimal values and Azure steps.
---

# Azure (AKS)

Inputs and outputs on Blob Storage (`az://container/blob`), from AKS.
Pick one way for `tif` and `tof` to get credentials. Executors get none
of them.

The examples assume release `poiesis` in namespace `poiesis`, so the
TaskPod ServiceAccount is `poiesis-taskpod`, and storage account
`poiesisdata`.

## Workload identity

1. Turn on the cluster's OIDC issuer:

   ```bash
   az aks update -g <group> -n <cluster> --enable-oidc-issuer
   ISSUER=$(az aks show -g <group> -n <cluster> \
     --query oidcIssuerProfile.issuerUrl -o tsv)
   ```

2. Create a managed identity, federate it with the TaskPod
   ServiceAccount, and give it access to the account:

   ```bash
   az identity create -g <group> -n poiesis-filer
   az identity federated-credential create -g <group> \
     --identity-name poiesis-filer --name poiesis-taskpod \
     --issuer "$ISSUER" \
     --subject system:serviceaccount:poiesis:poiesis-taskpod \
     --audiences api://AzureADTokenExchange
   az role assignment create --role "Storage Blob Data Contributor" \
     --assignee "$(az identity show -g <group> -n poiesis-filer --query principalId -o tsv)" \
     --scope "$(az storage account show -n poiesisdata --query id -o tsv)"
   ```

3. Install with:

   ```yaml
   azure:
     enabled: true
     accountName: poiesisdata
     clientId: <identity client ID>
     tenantId: <tenant ID>
   ```

Don't add the `azure.workload.identity/use` label or the
`azure.workload.identity/client-id` annotation: the webhook would inject
the token into executors too.

## Account key or SAS token

Put one of the two in the Secret:

```bash
kubectl -n poiesis create secret generic poiesis-azure \
  --from-literal=AZURE_STORAGE_ACCOUNT_KEY=…
# or a SAS with read, write and list permissions:
#   --from-literal=AZURE_STORAGE_SAS_TOKEN='sv=…&sig=…'
```

```yaml
azure:
  enabled: true
  accountName: poiesisdata
  existingSecret: poiesis-azure
```

A SAS token expires; tasks fail with an authorization error after that,
until the Secret holds a new one.

`azure.endpoint` points at another blob endpoint: a private endpoint
with its own DNS name, a sovereign cloud, or Azure Stack Hub.

## Two storage accounts

An `az://` URL names a container, not an account. To use a second
account, list its containers in `objectStores`; the default `azure`
block keeps the rest:

```yaml
objectStores:
  - name: archive
    provider: azure
    buckets: ["archive", "cold-*"] # containers
    accountName: labarchive
    existingSecret: poiesis-azure-archive # or clientId and tenantId
```

A container name can belong to one store only. See
[Several stores](../concepts/storage.md#several-stores).

## What is tested

CI runs `az://` inputs and outputs end to end against Azurite on kind,
with an account key and `azure.endpoint`, including a 20 MiB upload in
parts. SAS tokens and workload identity are covered by unit tests only;
neither has been run on AKS in CI. More in
[Storage and staging](../concepts/storage.md#azure-blob-storage).
