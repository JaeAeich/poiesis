# Authentication

Poiesis is a **resource server**: it validates OIDC bearer tokens
minted by an external Identity Provider (Keycloak, Auth0, Dex, Cognito,
…) and rejects anything else with `401`. It does not run a login flow,
issue tokens, or store passwords. Clients obtain a token from the IdP
and present it as `Authorization: Bearer <jwt>` on every request.

By default, authorization is an **owner-only rule**: every task row
carries a `principal` column, and callers see and cancel only the rows
whose `principal` equals the one named by their token. An optional
claim rule and an external decision service change that; see
[Authorization](./authorization.md).

## Configuration

The Helm chart exposes auth under `auth.oidc.*`. Values map 1:1 to the
`POIESIS_AUTH_*` environment variables on the API pod.

```yaml
auth:
  enabled: true
  oidc:
    issuer:          https://keycloak.example.org/realms/poiesis
    audience:        poiesis
    jwksCacheTtl:    3600    # seconds; lower = faster key-rotation pickup
    clockSkew:       30      # seconds of leeway on exp / nbf / iat
    timeout:         10      # seconds per call to the issuer
    principalClaim:  sub     # see "Principal claim" below
    requiredScopes:  []      # optional: reject tokens missing these
    userinfo:
      enabled:       false   # see "User info" below
```

`issuer` and `audience` are **required** when `enabled: true`. The
chart's JSON schema rejects empty values at `helm install` time so
misconfiguration surfaces immediately rather than as silent 401s.

There is no `clientSecret` in the chart — Poiesis is a resource
server, not an OAuth client, and never talks to the token endpoint.
The only network calls out go to the issuer: an anonymous GET of its
discovery document and JWKS endpoint, performed once at startup and
then refreshed lazily per `jwksCacheTtl`, and, if enabled, the
userinfo lookup (see "User info" below). `timeout`
(`POIESIS_AUTH_OIDC_TIMEOUT`, a positive number of seconds) bounds
each of these calls in total, from connecting to the last byte of the
answer; a slower answer at startup aborts the start.

## Disabling auth

For local development and air-gapped single-tenant deployments set
`auth.enabled: false`. The API then:

- skips OIDC discovery at startup (logs a `WARN`),
- accepts every request without a token,
- assigns each request a fixed anonymous principal,
- stamps the literal string `__anonymous__` on the `principal` column.

The downstream filter still runs — every anonymous caller shares one
bucket and sees the same tasks. Disabling auth does not "skip" the
column; it makes everyone the same owner.

## Principal claim

`principalClaim` names the JWT claim that identifies the owner. The
default `sub` works with every standards-compliant OIDC provider.

Dotted paths walk nested objects:

```yaml
auth:
  oidc:
    principalClaim: ctx.group_id
```

resolves to `claims["ctx"]["group_id"]`. This is useful when the IdP
groups tasks by tenant or group rather than per-user — every member of
group `alpha` then shares one principal and sees one another's tasks.

The claim must resolve to a non-empty string. Missing or non-string
values fail the request with `401 unauthorized`.

Only `sub` is a safe owner: claims that users can change at the IdP,
such as `email` or `preferred_username`, let one user take over
another's tasks.

### Worked example

Setting `principalClaim: ctx.group_id` with a Keycloak protocol-mapper
that nests `group_id` under `ctx`:

| User  | `sub` (per-user) | `ctx.group_id` (per-group) |
| ----- | ---------------- | -------------------------- |
| Alice | uuid-a           | `alpha`                    |
| Bob   | uuid-b           | `beta`                     |
| Carol | uuid-c           | `alpha`                    |

Under `principalClaim: sub` Alice and Carol see only their own tasks.
Under `principalClaim: ctx.group_id` Alice and Carol share visibility
into every task created by either of them; Bob stays isolated.

## Required scopes

`requiredScopes` is a global gate: a token whose `scope` claim does
not contain every listed scope is rejected with `403 forbidden`. This
is intentionally coarse — TES is a small API surface and per-endpoint
scopes were deferred to a later iteration. Leave the list empty
(default) to skip the check entirely.

## User info

Some IdPs release claims (e.g. group memberships such as
`eduperson_entitlement`) at the OIDC userinfo endpoint but not in
access tokens. With `userinfo.enabled: true`
(`POIESIS_AUTH_OIDC_USERINFO_ENABLED`), Poiesis calls that endpoint
for every validated token and keeps the answer on the principal, next
to (not merged into) the token claims:

- The endpoint comes from the issuer's discovery document; startup
  fails if it has none (or announces a plain `http` endpoint for an
  `https` issuer).
- The answer's `sub` must equal the token's `sub`.
- Answers are cached per token (keyed by a hash of it) until the token
  expires, but at most 5 minutes, which bounds how long a change at the
  IdP takes to show. The cache is bounded (least recently used
  tokens go first); parallel first requests with a new token may each
  call the endpoint.
- An outage (endpoint unreachable, slower than `timeout`, a `5xx`
  answer) is a `503 service_unavailable` with `Retry-After`, so clients
  retry instead of treating their token as bad. Any other failure (the
  token refused, a different `sub`, a non-JSON answer) is a
  `401 unauthorized`. Signed or encrypted userinfo (`application/jwt`)
  is not supported.
- A token without the principal claim is refused before the userinfo
  call, and one HTTP client per issuer is reused across calls.
- The token is sent to the userinfo endpoint only, never to any other
  service. The principal is still taken from the token.

Where a claim is looked up by name, Poiesis takes the access token's
value first and the userinfo value only if the token lacks the claim.
If your IdP can put the claims you need into the access token, prefer
that and leave userinfo off.

## What's enforced where

| Surface          | Enforcement                                                              |
| ---------------- | ------------------------------------------------------------------------ |
| HTTP handler     | `Depends(get_principal)` on every TES route. `service-info` is unauthed. |
| Database         | `tasks.principal` stamped on every insert; reads are scoped by authz.    |
| Workers          | TaskPods and `tctl` access the DB directly without a principal filter.   |

Workers (`trec`, `tctl`) act as the system, not on behalf of any user.
They are inside the trust boundary; the API tier is where authz
applies.

## Behaviour the client sees

- **No `Authorization` header** → `401 unauthorized` with body
  `{"error":"unauthorized","message":"missing bearer token"}`.
- **Malformed or expired token** → `401 unauthorized` with body
  `{"error":"unauthorized","message":"invalid token"}`. The reason
  (signature, audience, issuer, exp, …) is logged server-side at
  `WARNING` but not returned to the client.
- **Token missing a required scope** → `403 forbidden`.
- **`GET /tasks/{id}` of a task you don't own** → `404 not found`
  (deliberate: the policy does not leak the existence of resources you
  cannot see). Same for `POST /tasks/{id}:cancel`.
- **`GET /tasks`** → returns only tasks whose `principal` matches.

With a claim rule or a decision service, see
[Authorization](./authorization.md#behaviour-the-client-sees).

## How clients obtain a token

Out of Poiesis's scope, but the standard answers:

- **Workflow engines and CLIs**: OAuth 2.0 device flow against the
  configured issuer.
- **Service accounts** (CI, automated submitters): client-credentials
  grant. The token's `sub` is the service-account identifier and is
  stored verbatim on `tasks.principal` — service-account-owned tasks
  are first-class.
- **Interactive humans**: whatever your IdP's frontend uses
  (authorization code + PKCE for SPAs, etc.).

Poiesis accepts any valid token from the configured issuer. The IdP,
not Poiesis, decides who is allowed to authenticate.

## Migrating an existing deployment

The database migration adds `tasks.principal` with a backfill default
of `__legacy__`. Pre-existing rows are invisible to every real owner
once auth is on; the API logs a `WARN` at startup naming the count.
Reassign them with:

```sql
UPDATE tasks SET principal = '<new-owner>' WHERE principal = '__legacy__';
```

The default is dropped after the backfill, so all new inserts must
supply a principal — this is enforced at the route layer via
`Depends(get_principal)`.
