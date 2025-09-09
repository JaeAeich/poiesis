# Prerequisites

This section outlines the necessary tools and environment setup required before
deploying Poiesis.

## Kubernetes Cluster

A running Kubernetes cluster is essential for deploying Poiesis.

**For Local Development & Testing:**

If you're setting up Poiesis on your local machine for development or testing
purposes, several tools can help you create a single-node or multi-node
Kubernetes cluster easily, `Docker Desktop`, `Minikube`, `Kind` and `K3s` etc.

Choose one of these tools and follow its documentation to get a Kubernetes
cluster up and running.

**For Production Environments:**

For production deployments, a robust and resilient Kubernetes cluster is
crucial. Best practices include:

- **High Availability:** Deploy a cluster with at least three master nodes to
    ensure high availability of the Kubernetes control plane.
- **Worker Nodes:** Add a sufficient number of worker (or slave) nodes to run
    your application workloads. The number will depend on your application's
    resource requirements and desired fault tolerance.
- **Managed Kubernetes Services:** Consider using managed Kubernetes services
    from cloud providers (e.g., GKE, EKS) as they handle much of the
    underlying infrastructure management, scaling, and maintenance.

## Helm

Helm is the package manager for Kubernetes and is the recommended way to deploy
Poiesis and its dependencies. It simplifies the installation, configuration,
and management of complex Kubernetes applications.

**Installation:** If you don't already have Helm installed, follow the
[official Helm installation guide](https://helm.sh/docs/intro/install/) to set
it up on your client machine.

You can find Helm charts for `Poiesis` in its repository:
[Poiesis Helm Charts on GitHub](https://github.com/JaeAeich/poiesis/tree/main/deployment/helm).
