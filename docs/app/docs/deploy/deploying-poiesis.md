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

## Step 3: Enable Authentication with Keycloak

Previously we used a dummy Bearer token (`asdf`). Poiesis supports Keycloak for
real authentication.

:::warning Manual Management Ahead
The Helm chart handles deployment and secret creation only. Keycloak
configuration must be done manually.
:::

Enable Keycloak and set the auth type:

```bash
helm upgrade \
  --set minio.enabled=true \
  --set poiesis.auth.type=keycloak \
  --set keycloak.enabled=true \
  -n poiesis poiesis .
```

:::warning Keycloak Start Delay
Keycloak may take some time to initialize. Be patient if `kubectl port-forward`
doesn’t work immediately.
:::

Once ready, access the Keycloak admin UI:

```bash
kubectl port-forward svc/poiesis-keycloak 8080:80 -n poiesis
```

Visit [http://localhost:8080](http://localhost:8080) and log in with:

- **Username**: `keycloakUser123`
- **Password**: `keycloakPassword123`

### Keycloak Setup

1. Create a realm named `poiesis`.
2. Inside the realm, create a client named `poiesis`.

   - Enable **Client Authentication** and **Direct Access Grants**.
   - Set **Valid Redirect URIs** to `http://poiesis-api:8000/*`
   - Set **Web Origins** to `http://poiesis-api:8000/`
3. After creating the client, note down the **Client Secret**.

Let’s assume the secret is `client_secret_from_keycloak`.

Update your deployment with this secret:

```bash
helm upgrade \
  --set minio.enabled=true \
  --set poiesis.auth.type=keycloak \
  --set keycloak.enabled=true \
  --set poiesis.config.keycloakClientSecret=client_secret_from_keycloak \
  -n poiesis poiesis .
```

If the secret `poiesis-keycloak-secret` isn't updated (check its age), delete
and reapply:

```bash
kubectl delete secret keycloak-poiesis-secret -n poiesis
helm upgrade ... (same command as above)
```

Restart the API deployment to apply changes:

```bash
kubectl rollout restart deployment poiesis-api -n poiesis
```

### Create a User and Get a Token

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
    "description": "Testing Poiesis MinIO with Keycloak auth",
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
