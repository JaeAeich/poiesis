# Running Poiesis Locally (Dev Mode)

This guide will help you spin up all required services so you can run the Poiesis
API locally with hot reloading.

## Step 1: Set Up a Kubernetes Cluster

You can use any local Kubernetes setup like:

- Docker Desktop
- Minikube
- Kind

Make sure your cluster is up and running before proceeding.

## Step 2: Launch Dev Services

Apply the development Kubernetes manifest to start all dependent services in
the `po` namespace:

```bash
kubectl apply -f ./deployment/dev.yaml
```

:::info Namespace Info
The dev setup uses a dedicated namespace named `po` to isolate services and
keep things simple.
:::

### Choosing the Right Service Type

By default, the services in `dev.yaml` use `ClusterIP`. Depending on your setup,
you might need to change this:

- **If your local cluster supports direct network access (e.g. Docker Desktop):**
  Change the `spec.type` of services like MongoDB, Redis, and MinIO to `LoadBalancer`.
  This will expose them on local ports directly (make sure those ports are free).

- **If you're using `ClusterIP`:**
  Use `kubectl port-forward` to access services. Example for MongoDB:

  ```bash
  kubectl port-forward svc/poiesis-mongodb 27017:27017 -n po
  ```

## Step 3: Start the Dev Server

1. Copy `.envrc.template` to `.envrc` (if not already present).
2. Adjust environment variables to match any changes you've made in `dev.yaml`
    (e.g. ports, URLs).
3. Load the environment (if using `direnv`, it will auto-load).

Now, start the Poiesis API with hot reload:

```bash
make dev
```
