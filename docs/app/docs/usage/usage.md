# Poiesis, TES, and Its Applications

At its core, `Poiesis` allows you to describe *compute tasks over inputs* using
a standard schema, then schedules and executes those tasks within a
containerized environment.

Think of it this way: if your problem can be reduced to "*run this command with
these inputs and get the outputs*," then **Poiesis** can help you run it—at
scale, across systems, and with Kubernetes-level isolation.

## Why TES?

TES provides a **standard interface** to describe computational tasks, making
it easier to plug into different infrastructure without having to rewrite
execution logic. By implementing TES on Kubernetes, **Poiesis** brings this
standard to the cloud-native world, enabling seamless integration with:

- Bioinformatics pipelines
- Federated and multi-tenant platforms
- Workflow engines like `Cromwell`, `Nextflow`, or `Toil` etc
- Custom UIs or APIs that trigger compute jobs

## Poiesis as a Federated Task Layer

You can think of **Poiesis** as a **task execution abstraction** that sits
between a requestor (user, workflow engine, or system) and the Kubernetes
cluster. It decouples **who asks for the work** from **where and how it's run**.
This is especially powerful for:

- Multi-user scientific computing platforms
- Shared infrastructure in research organizations
- Data access governance (e.g., secure processing of protected datasets)
- Workload bursting across clusters or cloud providers

## What’s Ahead

The following pages will walk through **real-world use cases** where Poiesis can
serve as the intermediary layer to simplify compute orchestration in federated
or scalable systems.
