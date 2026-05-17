# Using Poiesis

Poiesis is a TES server. Anything that speaks TES can drive it:
workflow engines (Nextflow, Cromwell, Toil), client SDKs, or plain
`curl`. This section covers two concrete scenarios.

## Pick your client

- **`curl`** — fastest way to learn the API surface. The
  [deployment guide](../deploy/deploying-poiesis.md#submit-a-task)
  has working examples.
- **Workflow engines** — see [Nextflow](./nextflow.md). Most TES
  clients only need a base URL and (optionally) an S3 endpoint.
- **Programmatic** — the
  [TES OpenAPI spec](../intro/api-reference.md) is the contract.

## Common patterns

- **No-IO task** — just executors. Useful for smoke testing image
  pulls and Pod scheduling.
- **S3 in, S3 out** — `inputs[]` and `outputs[]` point at object
  storage; TIF stages onto `/transfer`, TOF uploads from `/transfer`.
- **Inline content** — `inputs[].content` carries the file body
  inline; no external storage needed.
- **Multi-executor** — executors run strictly sequentially through
  init-container ordering; the `/transfer` PVC persists between them.

## What Poiesis doesn't do

- **Schedule across clusters.** One TaskPod, one cluster.
- **Mutate your executor image.** Commands run exactly as submitted.
- **Cache anything.** Each submission is independent.
- **Run its own login flow.** Poiesis is a resource server, not an
  OAuth client. It validates OIDC bearer tokens minted by an external
  IdP (Keycloak, Auth0, Dex, …). See
  [Authentication](../deploy/authentication.md) for the operator
  configuration and the principal-claim model.
