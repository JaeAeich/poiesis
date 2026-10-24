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

## HTTP(S) outputs

An `outputs[].url` can be an `http://` or `https://` URL that grants
access by itself, such as a presigned upload URL from Amazon S3 or
Google Cloud Storage, so TOF needs no credentials for the client's
storage. TOF uploads each file with a `PUT` request that carries a
`Content-Length` header, as presigned upload URLs require.

- A presigned URL is signed for one object, so use one `FILE` output
  per presigned URL.
- For a `DIRECTORY` or glob output, TOF derives each file's URL by
  appending the file's relative path, escaped, to the path of the
  output URL, keeping its query string. Those URLs carry no valid
  signature, so point the output URL at a server that signs each upload
  as it arrives and redirects it to the storage provider.
- An upload follows a 307 or 308 redirect and sends the file again to
  the new URL. The first request carries the file too, so up to the
  whole file reaches a redirecting server, which can answer without
  reading it.
- A 301, 302 or 303 response fails the upload, because following it
  would turn the `PUT` into a `GET`. So does any other response outside
  2xx; the TOF log shows the start of the response body.
- The URL is stored with the task, including any signature in its query
  string, so issue presigned URLs with a short expiry.

## What Poiesis doesn't do

- **Schedule across clusters.** One TaskPod, one cluster.
- **Mutate your executor image.** Commands run exactly as submitted.
- **Cache anything.** Each submission is independent.
- **Run its own login flow.** Poiesis is a resource server, not an
  OAuth client. It validates OIDC bearer tokens minted by an external
  IdP (Keycloak, Auth0, Dex, …). See
  [Authentication](../deploy/authentication.md) for the operator
  configuration and the principal-claim model.
