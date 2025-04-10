# Poiesis

Poiesis is a task execution service that enables users to submit computational
tasks to be executed in containerized environments on Kubernetes. It fully
implements the `TES v1.1.0` specification while adding cloud-native capabilities
and security features.

:::info

`Poiesis` ships as a single binary/image, this makes the development as well
as deployment easier. It will be shipped as so, till the point increases the
size of the image per component doesn't outweigh the benefits.
:::

## Components

Poiesis is built with a modular architecture consisting of several key components:

### API

Poiesis uses [GA4GH TES](https://github.com/ga4gh/task-execution-schemas)
specification for the API as is with minimal alteration without changing the
semantics of the API.

:::tip

Install the `poiesis` CLI, run the info command to get what version and hash
of the TES specification is being used.
:::

### Core Services

The core services are the components that are responsible for the core functionality
of the Poiesis service, these directly interact with the Kubernetes API to manage
the lifecycle of the tasks.

Below is the list of the core services in the order of execution:

1. **TOrc**: Task Orchestrator
2. **TIF**: Task Input Filer
3. **TExAM**: Task Execution And Monitor
4. **TOF**: Task Output Filer

:::info

The `TE` is the actual task executor, it is a component that is not managed by
the Poiesis service, it is the actual task that is being executed, more than `Poiesis`,
the user is responsible for it.

Apart from these component, `Poiesis` also launches `PVC` per task, this `PVC` is
used to store the task's working directory.
:::

:::tip

Use info command on all of the core services to know more about them.
:::

### CLI

The `poiesis` CLI is a command line tool that allows users to interact with the
Poiesis service. It provides a way easily run `API` and the core services.

:::info

The `poiesis` CLI provides a much consistent interface to launch the core services
and the API, making it cleaner to express in K8s manifests.
:::
