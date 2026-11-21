---
description: The TES v1.1.0 endpoints under /ga4gh/tes/v1, Poiesis's own API key endpoints under /poiesis/v1, and the full OpenAPI document.
aside: false
outline: false
editLink: false
---

# TES API

Poiesis serves the GA4GH TES `v1.1.0` REST API under `/ga4gh/tes/v1`.

| Method | Path | Operation |
| --- | --- | --- |
| `GET` | `/service-info` | `GetServiceInfo` |
| `GET` | `/tasks` | `ListTasks` (filters, pagination, view levels) |
| `POST` | `/tasks` | `CreateTask` |
| `GET` | `/tasks/{id}` | `GetTask` (`MINIMAL`, `BASIC` or `FULL` view) |
| `POST` | `/tasks/{id}:cancel` | `CancelTask` |

Poiesis's own endpoints live under `/poiesis/v1`, outside the TES
namespace, and are mounted only when auth and API keys are on:

| Method | Path | Operation |
| --- | --- | --- |
| `POST` | `/api-keys` | `CreateApiKey` |
| `GET` | `/api-keys` | `ListApiKeys` (yours; `?owner=` an owner's, for admins) |
| `DELETE` | `/api-keys/{id}` | `RevokeApiKey` |
| `DELETE` | `/api-keys?owner=…` | `RevokeApiKeys` (all of an owner's, for admins) |

See [API keys](../concepts/api-keys.md) and
[Offboarding](../concepts/api-keys.md#offboarding).

Two more public routes:

- `GET /.well-known/oauth-protected-resource`: RFC 9728 metadata, when
  `auth.resource` is set. See [Discovery](../concepts/authentication.md#discovery).
- `GET /docs` and `GET /openapi.json` on a running server document both
  APIs, with an optional login; see
  [From the Swagger UI](../concepts/api-keys.md#from-the-swagger-ui).

<Callout type="info">

The OpenAPI document below is copied from the GA4GH repository at build
time. It is for reference only: the buttons don't call a live server.
Implementation-specific changes, if any, are syntactic and stay
compliant with the spec.

</Callout>

<SwaggerViewer />
