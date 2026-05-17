# Authentication

Poiesis is a **resource server**: it validates OIDC bearer tokens
minted by an external Identity Provider (Keycloak, Auth0, Dex, Cognito,
…) and rejects anything else with `401`. It does not run a login flow,
issue tokens, or store passwords. Clients obtain a token from the IdP
and present it as `Authorization: Bearer <jwt>` on every request.

Authorization is currently a **fixed owner-only filter**: every task
row carries a `principal` column and every read returns only the rows
whose `principal` equals the one named by the caller's token. A
pluggable `Authorizer` interface for richer policies (RBAC, groups,
labels) is on the roadmap; v1 hardcodes owner-only filtering as the
single policy.

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
    principalClaim:  sub     # see "Principal claim" below
    requiredScopes:  []      # optional: reject tokens missing these
```

`issuer` and `audience` are **required** when `enabled: true`. The
chart's JSON schema rejects empty values at `helm install` time so
misconfiguration surfaces immediately rather than as silent 401s.

There is no `clientSecret` in the chart — Poiesis is a resource
server, not an OAuth client, and never talks to the token endpoint.
The only network call out is an anonymous GET to the issuer's
discovery document and JWKS endpoint, performed once at startup and
then refreshed lazily per `jwksCacheTtl`.

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

## What's enforced where

| Surface          | Enforcement                                                              |
| ---------------- | ------------------------------------------------------------------------ |
| HTTP handler     | `Depends(get_principal)` on every TES route. `service-info` is unauthed. |
| Database         | `tasks.principal` stamped on every insert; reads filter on the column.   |
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
