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

:::warning ARM Architecture Compatibility (e.g., Apple Silicon Macs)

As of your last update, some third-party components, notably certain versions
or configurations of `bitnami/mongodb`, may have limitations or lack full
support for ARM-based architectures (like those found in Apple Silicon Macs).

If you are developing on an ARM-based machine, you might encounter issues with
these specific subcharts. Potential workarounds include:

- Using an alternative MongoDB deployment (e.g., a cloud-hosted MongoDB instance
or a self-managed instance compiled for ARM).

- Checking the Bitnami charts repository and MongoDB documentation for the
latest updates on ARM compatibility, as the situation may evolve.
:::

## Helm

Helm is the package manager for Kubernetes and is the recommended way to deploy
Poiesis and its dependencies. It simplifies the installation, configuration,
and management of complex Kubernetes applications.

**Installation:** If you don't already have Helm installed, follow the
[official Helm installation guide](https://helm.sh/docs/intro/install/) to set
it up on your client machine.

You can find Helm charts for `Poiesis` in its repository:
[Poiesis Helm Charts on GitHub](https://github.com/JaeAeich/poiesis/tree/main/deployment/helm).

## Subcharts (Dependencies)

Poiesis relies on several essential backend services to function correctly.
These services are managed as "subcharts" within the main Poiesis Helm chart.
This means that when you deploy Poiesis using Helm, these dependencies can be
deployed and configured automatically.

The primary subcharts used by Poiesis include:

- **MongoDB:** A NoSQL database used for data persistence.
- **MinIO:** An S3-compatible object storage service.
- **Keycloak:** An open-source identity and access management solution.
- **Redis:** An in-memory data structure store, used as a message broker.

The Helm charts for these components are primarily sourced from the
[Bitnami Helm charts repository](https://github.com/bitnami/charts), which
provides pre-packaged, validated, and secure applications for Kubernetes.
