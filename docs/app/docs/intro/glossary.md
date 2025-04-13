# Glossary

This glossary defines key terms and acronyms found in the Poiesis documentation.
It covers both Poiesis-specific components and general concepts relevant to the
[Task Execution Service (TES)](#task-execution-service-tes).

## Poiesis Components

Core services and components that make up the Poiesis system.

### Poiesis

Poiesis is a [Kubernetes](#kubernetes-k8s)-native implementation of the
[Task Execution Service (TES)](#task-execution-service-tes) specification.
It's designed to efficiently run computational [tasks](#task) within
[containerized](#container) environments on Kubernetes clusters.

### Task Orchestrator (TOrc)

*TOrc* is the Poiesis component that manages the setup and initialization
phase of a [task](#task). It ensures all necessary Kubernetes resources
(like [PVCs](#kubernetes-persistent-volume-claim-pvc)) and dependencies are
correctly provisioned before the task execution begins.

### Task Input Filer (TIF)

*TIF* is the Poiesis service responsible for importing input data required
by a [task](#task). It fetches files from user-specified storage locations
(supporting protocols like `S3`, `HTTPS`, direct `content`, local paths, etc.)
and makes them available to the task executor.

### Task Execution And Monitor (TExAM)

*TExAM* oversees the lifecycle of computational [tasks](#task) within Poiesis.
It handles submission, scheduling, resource allocation, monitoring execution
progress and logs, and managing results. `TExAM` is responsible for launching
the actual [Task Executor (TE)](#task-executor-te).

### Task Executor (TE)

*TE* is the component directly responsible for executing the commands defined
within a [task](#task). It runs within a [Kubernetes Pod](#kubernetes-pod) and
performs the actual computational work, utilizing the inputs prepared by
[TIF](#task-input-filer-tif) and generating outputs handled by [TOF](#task-output-filer-tof).

### Task Output Filer (TOF)

*TOF* is the Poiesis service that handles the export of output data generated
by a [task](#task). After task completion, *TOF* uploads specified files to the
user's desired storage location, using various supported protocols based on the
user's request.

## General Concepts

Fundamental terms related to container orchestration and task execution used in
the context of `Poiesis` and `TES`.

### Task Execution Service (TES)

*TES* is a standard specification developed by the Global Alliance for
Genomics and Health (GA4GH) for a RESTful API to submit, manage, and monitor
batch execution [tasks](#task). Poiesis implements this standard.

::: tip More Information
You can find the official TES specification on [GitHub](https://github.com/ga4gh/task-execution-schemas).
:::

### Container

A *container* is a lightweight, standalone, executable package of software
that includes everything needed to run it: code, runtime, system tools, system
libraries, and settings. Containers isolate software from its environment,
ensuring consistent operation. Popular containerization technology includes Docker.

### Task

In the context of [TES](#task-execution-service-tes), a *task* represents a
single unit of computational work. It's defined by its inputs (files, parameters),
outputs (expected files, logs), execution commands (typically run inside a
[container](#container)), and resource requirements (CPU, RAM, disk).

::: tip More Information
Check the task schema (`tesTask`) on the bottom section of the
[API Reference](./api-reference.md) page.
:::

### Kubernetes (K8s)

*Kubernetes* (often abbreviated as *K8s*) is an open-source platform for
automating the deployment, scaling, and management of [containerized](#container)
applications. Poiesis leverages Kubernetes to manage its components and execute
tasks efficiently.

::: tip More Information
Learn more at the [official Kubernetes website](https://kubernetes.io/).
:::

### Kubernetes Job

A *Kubernetes Job* is a controller object that creates one or more
[Pods](#kubernetes-pod) and ensures that a specified number of them
successfully terminate. Jobs are ideal for running batch processes or finite
[tasks](#task) to completion. `Poiesis` may use Jobs as part of its task execution
mechanism.

### Kubernetes Pod

A *Pod* is the smallest and simplest deployable unit in the
[Kubernetes](#kubernetes-k8s) object model. It represents a single instance of
a running process in your cluster and can contain one or more
[containers](#container), along with shared storage
([Volumes](#kubernetes-persistent-volume-claim-pvc)) and network resources.

### Kubernetes Persistent Volume Claim (PVC)

A *Persistent Volume Claim* (*PVC*) is a request for storage by a user within
[Kubernetes](#kubernetes-k8s). Pods can request specific storage resources
(like size and access modes) through PVCs, which are then fulfilled by
Persistent Volumes (PVs) available in the cluster. `Poiesis` uses PVCs to provide
persistent storage for [tasks](#task) when needed.
