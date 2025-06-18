# 🚀 Deploying `Poiesis`

This guide assumes you already have your Kubernetes cluster set up and Helm installed.

## Overview

The `values.yaml` file for Poiesis includes two important sections for managing dependencies:

- `.Values.poiesis.externalDependencies.<dependency_name>`
- `.Values.<dependency_name>`

This setup allows you to control whether Helm should deploy a specific component
for Poiesis or use an externally managed one. If you opt for the former, you’ll
need to provide configuration details (e.g., host, port, username, password).

This document walks through the deployment in a layered manner, starting with
the base components and progressively enabling others. Once familiar, you can
skip directly to the final step for a full deployment.

## Step 1: Deploy the Core Poiesis Service

Poiesis depends on two essential services:

- **MongoDB**: Stores task-related data.
- **Redis**: Powers internal messaging between services.

By default, dependencies in `values.yaml` are enabled
(`<dependency_name>.enabled=true`).

We’ll install Poiesis in a new namespace called... `poiesis` (naming is hard, okay?).

### Clone the Repository

```bash
git clone https://github.com/jaeaeich/poiesis.git
cd poiesis/deployment/helm
```

:::info `values.yaml`
The `values.yaml` file contains all configurable options for Poiesis. Once
you’re feeling adventurous, skim through the comments inside — there’s plenty
to tweak!
:::

### Install Poiesis

```bash
helm install poiesis . -n poiesis --create-namespace
```

🎉 *And voilà! Poiesis is installed.*

To expose the API and view the Swagger documentation:

```bash
kubectl port-forward svc/poiesis-api -n poiesis 8000:8000
```

:::info Swagger UI
Swagger is available at
[http://localhost:8000/ga4gh/tes/v1/ui](http://localhost:8000/ga4gh/tes/v1/ui).
You can submit tasks directly from the UI if you prefer that over `curl`.
:::

You can launch a task:

```bash
curl -X 'POST' \
  'http://localhost:8000/ga4gh/tes/v1/tasks' \
  -H 'accept: application/json' \
  -H 'Authorization: Bearer asdf' \
  -H 'Content-Type: application/json' \
  -d '{
  "name": "file-cat",
  "description": "Testing poiesis minio",
  "inputs": [
    {
      "content": "poiesis",
      "path": "/data/file1"
    }
  ],
  "resources": {
    "cpu_cores": 1,
    "preemptible": false,
    "ram_gb": 1,
    "disk_gb": 1
  },
  "executors": [
    {
      "image": "ubuntu:20.04",
      "command": [
        "/bin/cat",
        "/data/file1"
      ],
      "workdir": "/data/"
    }
  ]
}'
```

## Step 2: Add Object Storage (MinIO)

To enable object storage support via MinIO:

```bash
helm upgrade --set minio.enabled=true poiesis -n poiesis .
```

Now MinIO will be deployed alongside Poiesis.

### Access the MinIO Console

```bash
kubectl port-forward svc/poiesis-minio 9001:9001 -n poiesis
```

Navigate to [http://localhost:9001](http://localhost:9001) and log in with:

- **Username**: `minioUser123`
- **Password**: `minioPassword123`

You’ll see a default bucket named `poiesis`. Let's upload a test file to `poiesis/inputs/file`.

If you have the MinIO CLI (`mc`) installed:

```bash
kubectl port-forward svc/poiesis-minio 9000:9000 -n poiesis
echo "Poiesis" > /tmp/file
mc alias set minio http://localhost:9000 minioUser123 minioPassword123
mc cp /tmp/file minio/poiesis/inputs/file
```

You can now launch a task using this file:

```bash
curl -X 'POST' \
  'http://localhost:8000/ga4gh/tes/v1/tasks' \
  -H 'Authorization: Bearer asdf' \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "s3-file-cat",
    "description": "Testing Poiesis with MinIO",
    "inputs": [
      {
        "url": "s3://poiesis/inputs/file",
        "path": "/data/file"
      }
    ],
    "outputs": [
      {
        "path": "/data",
        "url": "s3://poiesis/outfile",
        "type": "DIRECTORY"
      }
    ],
    "resources": {
      "cpu_cores": 1,
      "ram_gb": 1,
      "disk_gb": 1,
      "preemptible": false
    },
    "executors": [
      {
        "image": "ubuntu:20.04",
        "command": ["/bin/cat", "/data/file"],
        "workdir": "/data/"
      }
    ]
  }'
```

Once the task completes, verify the output:

```bash
mc ls minio/poiesis
```

## Step 3: Enable Authentication with OIDC (Example: Keycloak)

By default, Poiesis uses a dummy Bearer token (`asdf`). For production, Poiesis
supports authentication via any OIDC (OpenID Connect) provider. Here, we show
how to use Keycloak as an example OIDC provider, but you can use any
OIDC-compliant service (e.g., Auth0, Okta, Google, etc.).

### 1. Install Keycloak (Example OIDC Provider)

First, install Keycloak in your cluster using the Bitnami Helm chart:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

helm install keycloak bitnami/keycloak \
  --namespace poiesis \
  --create-namespace \
  --set auth.adminUser=admin \
  --set auth.adminPassword=admin
```

Keycloak may take a few minutes to start. Once ready, access the Keycloak admin UI:

```bash
kubectl port-forward svc/keycloak 8080:80 -n poiesis
```

Visit [http://localhost:8080](http://localhost:8080) and log in with:

- **Username**: `admin`
- **Password**: `admin`

### 2. Configure Keycloak Realm and Client

1. **Create a realm** named `poiesis`.
2. **Create a client** named `poiesis` in the `poiesis` realm.
    - Enable **Client Authentication** and **Direct Access Grants**.
    - Set **Valid Redirect URIs** to `http://poiesis-api:8000/*`
    - Set **Web Origins** to `http://poiesis-api:8000/`
3. After creating the client, note down the **Client Secret**.

### 3. Configure Poiesis to Use OIDC

Update your deployment to use OIDC authentication by setting the following
values (either in `values.yaml` or via `helm upgrade --set ...`):

```bash
helm upgrade \
  --set minio.enabled=true \
  --set poiesis.auth.type=oidc \
  --set poiesis.auth.oidc.issuer=http://keycloak.poiesis.svc.cluster.local/realms/poiesis \
  --set poiesis.auth.oidc.clientId=poiesis \
  --set poiesis.auth.oidc.clientSecret=client_secret_from_keycloak \
  -n poiesis poiesis .
```

- Replace `client_secret_from_keycloak` with the actual client secret from Keycloak.
- Adjust the `issuer` URL if your Keycloak service uses a different address or
    if using an external OIDC provider.

If you update the client secret, you may need to delete and recreate the
relevant Kubernetes secret:

```bash
kubectl delete secret poiesis-keycloak-secret -n poiesis || true
helm upgrade ... (same command as above)
```

Restart the API deployment to apply changes:

```bash
kubectl rollout restart deployment poiesis-api -n poiesis
```

### 4. Create a User and Get a Token

1. In the `poiesis` realm, go to **Users → Create User**.
2. After creating, go to **Credentials**, set a password, and disable the
    "Temporary" flag.

Assume:

- Username: `jaeaeich`
- Password: `password`

Get a token:

```bash
curl -X POST "http://localhost:8080/realms/poiesis/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=poiesis" \
  -d "username=jaeaeich" \
  -d "password=password" \
  -d "client_secret=client_secret_from_keycloak"
```

Copy the `access_token` and use it to run authenticated tasks:

```bash
curl -X 'POST' \
  'http://localhost:8000/ga4gh/tes/v1/tasks' \
  -H 'Authorization: Bearer user_token_from_keycloak' \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "auth-s3-file-cat",
    "description": "Testing Poiesis MinIO with OIDC auth",
    "inputs": [
      {
        "url": "s3://poiesis/inputs/file",
        "path": "/data/file"
      }
    ],
    "outputs": [
      {
        "path": "/data",
        "url": "s3://poiesis/outfile",
        "type": "DIRECTORY"
      }
    ],
    "resources": {
      "cpu_cores": 1,
      "ram_gb": 1,
      "disk_gb": 1,
      "preemptible": false
    },
    "executors": [
      {
        "image": "ubuntu:20.04",
        "command": ["/bin/cat", "/data/file"],
        "workdir": "/data/"
      }
    ]
  }'
```
