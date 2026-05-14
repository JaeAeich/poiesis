---
# https://vitepress.dev/reference/default-theme-home-page
layout: home

hero:
  name: Poiesis
  text: TES on Kubernetes
  tagline: A single-Pod GA4GH TES v1.1 implementation backed by PostgreSQL
  image:
    src: /logo/logo.png
    alt: Poiesis Logo
  actions:
    - theme: brand
      text: Architecture
      link: /docs/dev/architecture
    - theme: alt
      text: Deploy
      link: /docs/deploy/deploying-poiesis

features:
  - title: GA4GH TES v1.1.0
    details: Conformant with the Task Execution Service spec. Workflow engines like Nextflow that speak TES point at Poiesis and just work.
  - title: Run anything as a task
    details: Bring your own container image and command. Poiesis honours it verbatim — no entrypoint wrapping, no command rewriting, no library injection.
  - title: Kubernetes-native, by design
    details: One Pod per task. Inputs and outputs stage onto a per-task volume. Resources, lifecycle, and cleanup map directly to Kubernetes primitives.
---
