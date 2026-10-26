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
storage. TOF streams each file from disk in a `PUT` request that
carries a `Content-Length` header, as presigned upload URLs require.

- A presigned URL is signed for one object, so use one `FILE` output
  per presigned URL.
- For a `DIRECTORY` or glob output, TOF derives each file's URL by
  appending the file's relative path, escaped, to the path of the
  output URL, keeping its query string. Those URLs carry no valid
  signature, so point the output URL at a server that signs each upload
  as it arrives and redirects it to the storage provider.
- If a glob matches no file, TOF uploads every file under `path_prefix`
  instead, as it does for every scheme. Behind a signing server, all of
  those files are signed and stored.
- An upload follows a 307 or 308 redirect and sends the file again to
  the new URL, unless the output URL is `https://` and the new URL
  isn't. The first request carries the file too, so up to the whole
  file reaches a redirecting server, which can answer without reading
  it.
- A 301, 302 or 303 response fails the upload, because following it
  would turn the `PUT` into a `GET`. So does any other response outside
  2xx; the TOF log shows the start of the response body.
- A 429, 500, 502, 503 or 504 response, a failed connection or a
  timeout is retried twice, after 1 s and then 2 s, each time from the
  output URL.
- TOF sets no size limit, but the storage provider caps a single `PUT`:
  at 5 GB on Amazon S3.
- TOF connects to whatever host the output URL or a redirect names,
  from the TaskPod's network, as the executors can. To limit where
  tasks can send data, restrict egress from the task namespace with a
  NetworkPolicy.
- Over `http://`, the URL, including any signature, and the file travel
  unencrypted, so use `https://` outside a trusted network.
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
