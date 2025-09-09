# Deploying Poiesis

This guide assumes you already have your Kubernetes cluster set up and Helm installed.

:::info A Note on Configuration Management
The examples in this guide use `helm --set` flags to explicitly show every
parameter being configured at each stage. This approach is intentionally
verbose for instructional clarity.

For any real-world deployment (including development, staging, or production),
the recommended practice is to use a dedicated values file
(e.g., `-f my-values.yaml`).
:::

## External Dependencies

External dependencies refer to the additional components that are required for
Poiesis to function properly. Namely MongoDB, Redis, and optional services like
object storage (e.g., MinIO).

The `.Values.poiesis.externalDependencies.<dependency_name>` section of the `values.yaml`
is used to configure that.

This document walks through the deployment in a layered manner, starting with
the base components and progressively enabling others. Once familiar, you can
skip directly to the final step for a full deployment.

## Prepare Dependencies

We will assume that you have already installed the external dependencies with
the preferred method to make them highly available, for example either using
operator-based installation or managed services.

For simplicity and demonstration purposes, we will use development installation
of some of the required services please refer to their official documentation for
a production setup.

### Clone the Repository

```bash
git clone https://github.com/jaeaeich/poiesis.git
cd poiesis/deployment/helm
```

### Install Dependencies

If not installed, install MongoDB, Redis, and MinIO via dev.yaml, we will use
`deps` namespace for dependencies (MongoDB, Redis, MinIO) and the poiesis
namespace for the Poiesis deployment.

```bash
kubectl apply -f ../dev.yaml -n deps --create-namespace
```

## Install Poiesis

```bash
helm install poiesis . \
  -n poiesis --create-namespace \
  --set externalDependencies.mongodb.connectionString="mongodb://admin:password@mongodb.deps.svc.cluster.local:27017/poiesis?authSource=admin" \
  --set externalDependencies.redis.host="redis.deps.svc.cluster.local" \
  --set externalDependencies.redis.port="6379" \
  --set externalDependencies.redis.auth.enabled=true \
  --set externalDependencies.redis.auth.password="password"
```

:::warning change the above settings as needed
This assumes that you have MongoDB and redis installed with above credentials.
:::

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

## Add Object Storage (MinIO)

To enable object storage support via MinIO, we will upgrade the deployment to
include MinIO.

```bash
helm upgrade --install poiesis . \
  -n poiesis --create-namespace \
  --set externalDependencies.mongodb.connectionString="mongodb://admin:password@mongodb.deps.svc.cluster.local:27017/poiesis?authSource=admin" \
  --set externalDependencies.redis.host="redis.deps.svc.cluster.local" \
  --set externalDependencies.redis.port="6379" \
  --set externalDependencies.redis.auth.enabled=true \
  --set externalDependencies.redis.auth.password="password" \
  --set externalDependencies.minio.enabled=true \
  --set externalDependencies.minio.url="http://minio.deps.svc.cluster.local:9000" \
  --set externalDependencies.minio.auth.rootUser="admin" \
  --set externalDependencies.minio.auth.rootPassword="password"
```

Now Poiesis will be configured with MinIO.

### Put Data into MinIO

:::info Optional
This is optional, added here just for the sake of completion.
:::

```bash
kubectl port-forward svc/minio 9001:9001 -n deps
```

Navigate to [http://localhost:9001](http://localhost:9001) and log in with:

- **Username**: `admin`
- **Password**: `password`

Create a bucket named `poiesis` and let's upload a test file to `poiesis/inputs/file`.

If you have the MinIO CLI (`mc`) installed:

```bash
kubectl port-forward svc/minio 9000:9000 -n deps
echo "Poiesis" > /tmp/file
mc alias set minio http://localhost:9000 admin password
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

## Enable Authentication with OIDC (Example: Keycloak)

By default, Poiesis uses a dummy Bearer token (`asdf`). For production, Poiesis
supports authentication via any OIDC (OpenID Connect) provider. Here, we show
how to use Keycloak as an example OIDC provider, but you can use any
OIDC-compliant service (e.g., Auth0, Okta, Google, etc.).

### Configure Keycloak Realm and Client

1. **Create a realm** named `poiesis`.
2. **Create a client** named `poiesis` in the `poiesis` realm.
    - Enable **Client Authentication** and **Direct Access Grants**.
    - Set **Valid Redirect URIs** to `http://poiesis-api:8000/*`
    - Set **Web Origins** to `http://poiesis-api:8000/`
3. After creating the client, note down the **Client Secret**.

### Configure Poiesis to Use OIDC

Update your deployment to use OIDC authentication by setting the following
values (either in `values.yaml` or via `helm upgrade --set ...`):

```bash
helm upgrade \
    -n poiesis --create-namespace \
    --set externalDependencies.mongodb.connectionString="mongodb://admin:password@mongodb.deps.svc.cluster.local:27017/poiesis?authSource=admin" \
    --set externalDependencies.redis.host="redis.deps.svc.cluster.local" \
    --set externalDependencies.redis.port="6379" \
    --set externalDependencies.redis.auth.enabled=true \
    --set externalDependencies.redis.auth.password="password" \
    --set externalDependencies.minio.enabled=true \
    --set externalDependencies.minio.url="http://minio.deps.svc.cluster.local:9000" \
    --set externalDependencies.minio.auth.rootUser="admin" \
    --set externalDependencies.minio.auth.rootPassword="password" \
    --set poiesis.auth.type=oidc \
    --set poiesis.auth.oidc.issuer=http://keycloak.poiesis.svc.cluster.local/realms/poiesis \
    --set poiesis.auth.oidc.clientId=poiesis \
    --set poiesis.auth.oidc.clientSecret=client_secret_from_keycloak \
    -n poiesis poiesis .
```

- Replace `client_secret_from_keycloak` with the actual client secret from Keycloak.
- Adjust the `issuer` URL if your Keycloak service uses a different address or
    if using an external OIDC provider.

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
  -d "client_secret=client_secret_from_keycloak" \
  -d "scope=openid"
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
