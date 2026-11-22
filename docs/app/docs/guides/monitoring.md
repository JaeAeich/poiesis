---
description: Scrape Poiesis with Prometheus - the API and TCtl metrics endpoints, every metric and its labels, a Grafana dashboard and alert rules.
---

# Monitoring

The API and TCtl serve [Prometheus](https://prometheus.io) metrics at
`/metrics`. They show whether Poiesis is healthy (a leader, passes that
succeed, few 5xx) and how loaded it is (request rate, tasks by state,
how long the oldest task has been queued, database pool use).

## The endpoints

- Each API and TCtl Pod serves `/metrics` on `metrics.port` (`9090`),
  apart from the TES API's port `8000`. The Ingress and the API Service
  never route to it, it needs no authentication and it is not in the
  access log.
- The chart renders a Service per component for it:
  `<release>-api-metrics` and `<release>-tctl-metrics`, port `metrics`.
- `metrics.enabled: false` turns the endpoints, the port and the
  Services off. Without the chart, set `POIESIS_METRICS_PORT` on the API
  and TCtl; unset, no endpoint is served.
- The API runs one process per Pod, so each Pod's endpoint has all of its
  metrics. Scale and scrape by Pod.

Check an endpoint by hand:

```sh
kubectl -n poiesis port-forward svc/poiesis-api-metrics 9090:9090 &
curl -s localhost:9090/metrics | grep ^poiesis_
```

## Scraping

With the [Prometheus Operator](https://prometheus-operator.dev), turn on
the ServiceMonitor and give it the labels your Prometheus selects:

```yaml
metrics:
  serviceMonitor:
    enabled: true
    labels:
      release: kube-prometheus-stack
    interval: 30s
```

It needs the `monitoring.coreos.com` CRDs; nothing else in the chart
does.

A Prometheus that discovers Pods by annotation gets
`prometheus.io/scrape`, `/port` and `/path` on the API and TCtl Pods with
`metrics.scrapeAnnotations: true`.

With `networkPolicy.enabled`, the metrics port is open to
`networkPolicy.metricsFrom`; empty (the default) opens it to any address.
Narrow it to your Prometheus:

```yaml
networkPolicy:
  enabled: true
  metricsFrom:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
```

## Metrics

Labels have bounded values. No metric has a task id, user, owner or raw
path label, so the number of series doesn't grow with the number of
tasks or users.

### API

| Metric                                  | Type      | Labels                      | Meaning                                                                                                                                                                                                                                                                                    |
| --------------------------------------- | --------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `poiesis_http_requests_total`           | counter   | `method`, `route`, `status` | HTTP requests answered. `route` is the path template, e.g. `/ga4gh/tes/v1/tasks/{id}`; `unmatched` for a path no route serves. Other methods: `other`.                                                                                                                                     |
| `poiesis_http_request_duration_seconds` | histogram | `method`, `route`, `status` | Time to answer a request.                                                                                                                                                                                                                                                                  |
| `poiesis_http_requests_in_progress`     | gauge     |                             | Requests being served now.                                                                                                                                                                                                                                                                 |
| `poiesis_task_submissions_total`        | counter   | `outcome`                   | CreateTask requests: `created`, `rejected` (`400` before anything is written, e.g. an unsupported URL scheme), `submit_failed` (Kubernetes refused the Job or PVC, or didn't answer; the task ends `SYSTEM_ERROR`). A body that fails validation is only in `poiesis_http_requests_total`. |
| `poiesis_db_pool_size`                  | gauge     |                             | Connections the pool has open.                                                                                                                                                                                                                                                             |
| `poiesis_db_pool_max_size`              | gauge     |                             | Connections the pool may open (`database.pool.maxSize`).                                                                                                                                                                                                                                   |
| `poiesis_db_pool_in_use`                | gauge     |                             | Connections lent out to requests.                                                                                                                                                                                                                                                          |
| `poiesis_db_pool_waiters`               | gauge     |                             | Requests waiting for a connection. A request that waits longer than `database.pool.acquireTimeoutSeconds` gets a `503`.                                                                                                                                                                    |

The API also exports the Prometheus client's `process_*` and
`python_*` metrics (CPU, memory, open files, garbage collection).

### TCtl

| Metric                                                  | Type      | Labels            | Meaning                                                                                                                                                                                                                                                                                                       |
| ------------------------------------------------------- | --------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `poiesis_tctl_is_leader`                                | gauge     |                   | `1` while this instance holds the leader Lease. The sum over replicas should be `1`.                                                                                                                                                                                                                          |
| `poiesis_tctl_reconcile_duration_seconds`               | histogram |                   | Time of one reconcile pass.                                                                                                                                                                                                                                                                                   |
| `poiesis_tctl_reconcile_last_success_timestamp_seconds` | gauge     |                   | Unix time the last pass ended without an error.                                                                                                                                                                                                                                                               |
| `poiesis_tctl_reconcile_errors_total`                   | counter   |                   | Passes that raised (Postgres down, a Job or Pod list that failed).                                                                                                                                                                                                                                            |
| `poiesis_tasks`                                         | gauge     | `state`           | Tasks in the database, by TES state. Leader only.                                                                                                                                                                                                                                                             |
| `poiesis_tasks_oldest_age_seconds`                      | gauge     | `state`           | Age of the oldest task in each non-terminal state, `0` when there is none. Leader only.                                                                                                                                                                                                                       |
| `poiesis_tctl_terminal_transitions_total`               | counter   | `state`, `reason` | Terminal states TCtl wrote. `reason` is the check that ended the task: `pod-terminal`, `job-deadline`, `job-failed`, `job-complete`, `pending-timeout`, `unschedulable-timeout`, `terminating-timeout`, `orphan`. A write that lands as `CANCELED` because the task was being cancelled counts as `CANCELED`. |
| `poiesis_tctl_kubernetes_errors_total`                  | counter   | `operation`       | Kubernetes calls that failed: `lease`, `list_jobs`, `list_pods`, `list_events`, `delete_job`.                                                                                                                                                                                                                 |
| `poiesis_tctl_lease_renew_failures_total`               | counter   |                   | Lease renewals that failed, each ending a leadership term.                                                                                                                                                                                                                                                    |

The task gauges come from one grouped query that the leader runs at most
every 30 seconds; a standby leaves them out, so `max` or `sum` over the
TCtl Pods counts each task once. Terminal states written by the API (a
failed submission) are not in `poiesis_tctl_terminal_transitions_total`;
they are `poiesis_task_submissions_total{outcome="submit_failed"}`.

## Dashboard

`deployment/helm/poiesis/dashboards/poiesis.json` is a Grafana dashboard
with the request rate, errors and latency by route, submissions, tasks
by state, the oldest task's age, reconcile duration, the leader count,
the database pool and TCtl's errors. Import it in Grafana, or let the
chart put it in a ConfigMap for the Grafana sidecar:

```yaml
metrics:
  dashboard:
    enabled: true
    labels:
      grafana_dashboard: "1"
```

## Alert rules

An example `PrometheusRule`. Tune the thresholds to your load: how long a
task may stay queued depends on your cluster's capacity and on
`tctl.unschedulableTimeoutSeconds`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: poiesis
  namespace: poiesis
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: poiesis
      rules:
        - alert: PoiesisApiErrors
          expr: |
            sum(rate(poiesis_http_requests_total{status=~"5.."}[5m]))
              / sum(rate(poiesis_http_requests_total[5m])) > 0.05
          for: 10m
          labels: { severity: warning }
          annotations:
            summary: More than 5% of Poiesis API requests fail with 5xx.
        - alert: PoiesisNoLeader
          expr: sum(poiesis_tctl_is_leader) < 1 or absent(poiesis_tctl_is_leader)
          for: 5m
          labels: { severity: critical }
          annotations:
            summary: No TCtl holds the leader Lease; no task reaches a final state.
        - alert: PoiesisReconcileStalled
          expr: |
            time() - max(poiesis_tctl_reconcile_last_success_timestamp_seconds) > 300
          for: 5m
          labels: { severity: critical }
          annotations:
            summary: TCtl has not finished a reconcile pass in 5 minutes.
        - alert: PoiesisTaskQueuedTooLong
          expr: max(poiesis_tasks_oldest_age_seconds{state="QUEUED"}) > 3600
          for: 15m
          labels: { severity: warning }
          annotations:
            summary: A task has been QUEUED for more than an hour.
        - alert: PoiesisDatabasePoolSaturated
          expr: |
            max by (pod) (poiesis_db_pool_waiters) > 0
              and max by (pod) (poiesis_db_pool_in_use)
                >= max by (pod) (poiesis_db_pool_max_size)
          for: 5m
          labels: { severity: warning }
          annotations:
            summary: An API Pod's database pool is full and requests are waiting.
```

`absent()` in `PoiesisNoLeader` also fires when Prometheus scrapes no
TCtl at all.

## Not covered

- **Tracing.** There are no OpenTelemetry traces yet. Follow one
  request or task through the logs, by `request_id` or `task_id`
  ([Logs](./production.md#logs)).
- **Per-task metrics**, by design: a task, user or owner label would
  make a series per task. Use the TES API (`GET /tasks/{id}`) and the
  logs for one task.
- TaskPods (`trec`, `tif`, `tof`) export no metrics. A staging failure
  shows in the task's final state, counted in `poiesis_tasks`, and in its
  `system_logs`.
