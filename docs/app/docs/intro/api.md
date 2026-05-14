# API

Poiesis serves the GA4GH TES `v1.1.0` REST API under `/ga4gh/tes/v1`.

| Method | Path | Operation |
| --- | --- | --- |
| `GET` | `/service-info` | `GetServiceInfo` |
| `GET` | `/tasks` | `ListTasks` (filters, pagination, view levels) |
| `POST` | `/tasks` | `CreateTask` |
| `GET` | `/tasks/{id}` | `GetTask` (`MINIMAL` / `BASIC` / `FULL` view) |
| `POST` | `/tasks/{id}:cancel` | `CancelTask` |

The [API Reference](./api-reference.md) renders the full OpenAPI spec.

::: info Source of truth
The OpenAPI document is copied verbatim from the GA4GH repository at
build time. Implementation-specific changes (if any) are syntactic and
remain compliant with the spec.
:::
