# Poiesis: Kubernetes-Native Task Execution

`Poiesis` is a robust Task Execution Service (TES) designed specifically for
running computational tasks efficiently within containerized environments on
Kubernetes. It offers a fully compliant implementation of the *GA4GH* `TES
v1.1.0` specification, enhanced with cloud-native capabilities and security
features tailored for modern infrastructure.

::: info Packaging
`Poiesis` is distributed as a **single binary/image**. This approach simplifies
both development workflows and deployment processes significantly. I plan to
maintain this single artifact model as long as the benefits outweigh potential
size considerations for individual components.
:::

## Architecture Overview

`Poiesis` features a modular architecture built around distinct components that
work together to manage the entire lifecycle of a task on Kubernetes. At a high
level, it consists of:

1.**API Endpoint:** Exposes the TES v1.1.0 compliant interface for clients.

2.**Core Services:** The backend engine that interacts directly with the
    Kubernetes API to orchestrate, execute, and monitor tasks.

3.**CLI Tool (`poiesis`):** A command-line utility for interacting with the
    service and managing its components.

This architecture, packaged into a single deployable unit, provides a powerful
yet manageable solution for task execution.

## Components

### API (TES v1.1.0 Compliant)

The Poiesis API strictly adheres to the
[GA4GH TES v1.1.0 specification](https://github.com/ga4gh/task-execution-schemas).
It provides the standard RESTful endpoints for submitting tasks, querying their
status, and retrieving results, ensuring compatibility with existing TES clients
and workflows.

::: tip Check TES Version
You can easily verify the exact `TES` specification version and commit hash
implemented by your `Poiesis` instance by running the `poiesis info` command
using the [CLI](./cli.md).
:::

### Core Services

These services form the operational backbone of `Poiesis`, directly managing
task execution on the Kubernetes cluster. They typically run in sequence for
each task:

1.**`TOrc` (Task Orchestrator):** Initializes the task run by setting up
    necessary Kubernetes resources, such as creating a Persistent Volume
    Claim (`PVC`) and starting the `TExAM` job.

2.**`TIF` (Task Input Filer):** Prepares the execution environment by
    downloading and staging all required input files into the task's workspace
    (mounted PVC).

3.**`TExAM` (Task Execution And Monitor):** Launches the actual **Task Executor
    (`TE`)** container (defined by the user's task request) and continuously
    monitors its status, resource usage, and logs.

4.**`TOF` (Task Output Filer):** After the `TE` completes, `TOF` collects
    specified output files from the task's workspace and uploads them to the
    designated output storage location(s).

::: info The Role of the Task Executor (TE)
It's important to note that the **`TE` (Task Executor)** itself is *not* a
static part of the `Poiesis` service infrastructure. Instead, it represents the
**user-defined workload container** specified in the `TES` Task request.
`Poiesis` (specifically `TExAM`) is responsible for *launching, managing, and
monitoring* this `TE` container, but the container image, commands, and resource
requests are defined by the user submitting the task.
:::

::: info Per-Task PVC
`Poiesis` typically provisions a dedicated **Kubernetes Persistent Volume Claim
(`PVC`)** for each task. This PVC serves as the isolated working directory where
inputs are staged, computations occur, and outputs are generated before being
collected by `TOF`. For privacy and security of sensitive data, PVCs are
automatically deleted after task completion.
:::

### CLI

The `poiesis` Command Line Interface (CLI) is a versatile tool for interacting
with the `Poiesis` service. It is exactly like the API but handles much more
than the simple user facing API endpoints.

::: warning With great power comes great responsibility
The `poiesis` CLI is designed for advanced users who want to interact with the
`Poiesis` service in a more dynamic and flexible way. It is not recommended for
users who only need to submit tasks and retrieve results. Read the
[CLI](./cli.md) page for more information.
:::
