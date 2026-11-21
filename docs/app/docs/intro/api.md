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

Poiesis's own endpoints live under `/poiesis/v1`, outside the TES
namespace, and are mounted only when auth and API keys are on:

| Method | Path | Operation |
| --- | --- | --- |
| `POST` | `/api-keys` | `CreateApiKey` |
| `GET` | `/api-keys` | `ListApiKeys` (yours; `?owner=` an owner's, for admins) |
| `DELETE` | `/api-keys/{id}` | `RevokeApiKey` |
| `DELETE` | `/api-keys?owner=…` | `RevokeApiKeys` (all of an owner's, for admins) |

See [API keys](../deploy/api-keys.md) and
[Offboarding](../deploy/api-keys.md#offboarding). A running server
documents both at `/docs` (Swagger UI) and `/openapi.json`.

::: info Source of truth
The OpenAPI document is copied verbatim from the GA4GH repository at
build time. Implementation-specific changes (if any) are syntactic and
remain compliant with the spec.
:::
