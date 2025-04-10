# Glossary

This glossary provides definitions for key terms and acronyms used throughout
the Poiesis documentation, some of the terms are specific to Poiesis and some
are general terms used in the context of [TES](#tes).

## Poiesis

A [Kubernetes](#kubernetes)-native implementation of the
[Task Execution Service (TES)](#tes) specification, designed to run
computational [tasks](#task) efficiently in [containerized](#container)
environments.

### TIF

**Task Input Filer** - A core service of [Poiesis](/docs/intro/poiesis) that
handles import of data and files that the user requests to be used in the
[task](#task). [TIF](#tif) is responsible for downloading the files from the
user's storage and making them available to the task.

[TIF](#tif) supports multiple protocols which are easily extensible such as `S3`,
`content`, `local` and more.

### TOF

**Task Output Filer** - A core service of [Poiesis](/docs/intro/poiesis) that
handles export of data and files that the user requests to be used in the
[task](#task). [TOF](#tof) is responsible for uploading the files to the user's
storage and making them available to the task.

[TOF](#tof) supports multiple protocols which are easily extensible, and based
on user request, the data gets uploaded to the correct storage location.

### TExAM

**Task Execution And Monitor** - A comprehensive approach to handling
computational [tasks](#task) that includes submission, scheduling, resource allocation,
execution, monitoring, and result handling.

[TExAM](#texam) launches [TE](#te) and monitors their status and logs.

### TOrc

**Task Orchestrator** - A core component within [Poiesis](/docs/intro/poiesis)
that manages the orchestration and initialization of a [task](#task).
[TOrc](#torc) is responsible for creating the necessary resources and
dependencies for a task to run.

### TE

**Task Executor** - A core component within [Poiesis](/docs/intro/poiesis) that
executes a [task](#task). [TE](#te) is responsible for running the task and
returning the results to the user.

## General Terms

### TES

**Task Execution Service** - A specification for a RESTful API that allows users
to submit [tasks](#task) to be executed by a worker. [TES](#tes) provides a
standardized way to describe batch execution tasks. For more information, see
the [TES specification](https://github.com/ga4gh/task-execution-schemas).

### Container

A lightweight, standalone, executable software package that includes everything
needed to run a piece of software, including the code, runtime, system tools,
libraries, and settings.

### Task

A unit of work submitted to [TES](#tes) for execution, defined by its inputs,
outputs, and the commands to be executed. For more information see the
[TES specification](https://github.com/ga4gh/task-execution-schemas).

### Kubernetes

An open-source [container](#container) orchestration platform that automates the
deployment, scaling, and management of containerized applications. Learn more at
the [official Kubernetes website](https://kubernetes.io/).

### Kubernetes Job

A [Kubernetes](#kubernetes) Job is a controller that creates one or more
[Pods](#kubernetes-pod) to run [tasks](#task) until completion. Jobs ensure that
a specified number of Pods successfully terminate, making them ideal for batch
processes, finite tasks, and one-time executions. Unlike regular Pods, Jobs
track task completion and can handle retries on failure.

### Kubernetes Pod

A [Kubernetes](#kubernetes) Pod is the smallest deployable unit in Kubernetes
that represents a single instance of a running process. It encapsulates one or
more [containers](#container), shared storage volumes, network resources
(with a unique IP address), and specifications for how to run the containers.
Pods serve as the basic building block for deployment in the Kubernetes ecosystem.

### Kubernetes PVC

A [Kubernetes](#kubernetes) Persistent Volume Claim (PVC) is a request for storage
by a user. PVCs are used to request storage from the Kubernetes cluster.
