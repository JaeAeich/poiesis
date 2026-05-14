# Task Execution Service (TES)

TES is a [GA4GH](https://www.ga4gh.org/) Cloud Work Stream standard for
a RESTful API that submits, manages, and monitors batch computational
tasks. It was developed to make large-scale genomic analyses portable
across compute environments — but the contract is general-purpose: any
batch workload that fits "run this command with these inputs and
collect these outputs" is in scope.

A TES task declares:

- A sequenced list of `executors` (image + command + env + workdir).
- Optional `inputs` (URLs to stage onto a shared volume).
- Optional `outputs` (paths to upload after the executors run).
- `resources` (CPU, RAM, disk).

The server schedules execution and reports back state, per-executor
logs, and termination reasons. Poiesis implements the server side on
Kubernetes.

[Specification on GitHub](https://github.com/ga4gh/task-execution-schemas).
