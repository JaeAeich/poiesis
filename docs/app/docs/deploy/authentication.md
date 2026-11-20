# Authentication

Poiesis is a **resource server**: it validates signed bearer tokens
(JWTs) minted by one or more trusted issuers (Keycloak, Auth0, Dex,
Cognito, GitHub Actions OIDC, a gateway, …) and rejects anything else
with `401`. It does not run a login flow, issue tokens, or store
passwords. Clients obtain a token from an issuer and present it as
`Authorization: Bearer <jwt>` on every request.

By default, authorization is an **owner-only rule**: every task row
carries an `owner` column, and callers see and cancel only the rows
whose `owner` is their own. An optional claim rule and an external
decision service change that; see [Authorization](./authorization.md).

## Configuration

The Helm chart lists the trusted issuers under `auth.issuers`. The
list reaches the API pod as one environment variable,
`POIESIS_AUTH_ISSUERS`, a JSON array with the same (camelCase) keys.

```yaml
auth:
  enabled: true
  issuers:
    - issuer:          https://keycloak.example.org/realms/poiesis
      audience:        poiesis
      principalClaim:  sub     # see "Owner and principal claim" below
      requiredScopes:  []      # optional: reject tokens missing these
      userinfo:
        enabled:       false   # see "User info" below
      jwksCacheTtl:    3600    # seconds to cache the issuer's keys
      clockSkew:       30      # seconds of leeway on exp / nbf / iat
      timeout:         10      # seconds per call to the issuer
    # A gateway (Envoy, Istio, oauth2-proxy) that signs its own JWTs
    # and publishes only its keys: no discovery, no userinfo.
    - issuer:          https://gateway.example.org
      audience:        poiesis
      jwksUri:         http://gateway.mesh.svc/.well-known/jwks.json
```

The same configuration as environment variables:

```bash
POIESIS_AUTH_ENABLED=true
POIESIS_AUTH_ISSUERS='[
  {"issuer": "https://keycloak.example.org/realms/poiesis", "audience": "poiesis"},
  {"issuer": "https://gateway.example.org", "audience": "poiesis",
   "jwksUri": "http://gateway.mesh.svc/.well-known/jwks.json"}
]'
```

Each entry needs `issuer` and `audience`; everything else has the
defaults shown. Poiesis refuses to start (and the chart's JSON schema
refuses to install) when auth is enabled with no issuer, an entry lacks
`issuer` or `audience`, an issuer is listed twice, an entry has an
unknown key, or `userinfo` is combined with `jwksUri`. The old
`auth.oidc.*` values and `POIESIS_AUTH_OIDC_*` variables are gone: any
`POIESIS_AUTH_OIDC_*` variable left in the environment refuses to start,
naming `POIESIS_AUTH_ISSUERS` as its replacement.

There is no `clientSecret` — Poiesis is a resource server, not an OAuth
client, and never talks to a token endpoint. The only network calls go
to the configured issuers: an anonymous GET of the discovery document
(`<issuer>/.well-known/openid-configuration`, unless `jwksUri` is set)
and of the JWKS, and, if enabled, the userinfo lookup. `timeout` (a
positive number of seconds) bounds each of these calls in total, from
connecting to the last byte of the answer.

## How a token finds its issuer

Poiesis reads the token's `iss` claim (unverified) and looks it up in
the configured list, by **exact** string match: a trailing `/` matters.
A token from any other issuer is a `401`. Keys are only ever fetched
from the configured issuer's discovery document or `jwksUri`, never from
a URL the token names. The token is then verified in full against that
issuer: signature (RS, ES or PS algorithms), `iss`, `aud`, `exp` with
`clockSkew` of leeway, and the issuer's `requiredScopes`.

The discovery document's own `issuer` must equal the configured
`issuer` exactly; otherwise the issuer is misconfigured (see below).
The `jwks_uri` and `userinfo_endpoint` it announces must be absolute
`https` URLs (`http` only if the issuer is `http` too).

Identity only ever comes from a token Poiesis verifies itself. Plain
headers such as `X-User`, `X-Forwarded-User` or `Remote-User` are
ignored, also behind a proxy: a gateway that authenticates users in its
own way (SAML, LDAP, mTLS) must sign a JWT for Poiesis and be listed as
an issuer, usually with `jwksUri`.

## Owner and principal claim

The owner stamped on every task is the opaque string
`<issuer>|<subject>`, where `<subject>` is the value of the issuer's
`principalClaim` (default `sub`). Two issuers that issue the same `sub`
therefore never share tasks:

| Caller | Issuer | `sub` | Owner |
| --- | --- | --- | --- |
| Alice | `https://kc.example.org/realms/poiesis` | `uuid-a` | `https://kc.example.org/realms/poiesis\|uuid-a` |
| CI | `https://token.actions.githubusercontent.com` | `repo:org/x:ref:refs/heads/main` | `https://token.actions.githubusercontent.com\|repo:org/x:ref:refs/heads/main` |

Dotted paths walk nested objects:

```yaml
auth:
  issuers:
    - issuer: https://keycloak.example.org/realms/poiesis
      audience: poiesis
      principalClaim: ctx.group_id
```

resolves to `claims["ctx"]["group_id"]`. This is useful when the IdP
groups tasks by tenant or group rather than per-user — every member of
group `alpha` then shares one owner and sees one another's tasks.

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

`requiredScopes` is a per-issuer gate: a token whose `scope` (or `scp`)
claim does not contain every listed scope is rejected with
`403 forbidden`. This is intentionally coarse — TES is a small API
surface and per-endpoint scopes were deferred to a later iteration.
Leave the list empty (default) to skip the check.

## Issuer outages and key rotation

Poiesis keeps working through issuer outages and key rotations, per
issuer:

- **Soft start.** At startup each issuer is bootstrapped (discovery,
  then keys). If an issuer is unreachable, slower than `timeout`, or
  answers `5xx`, `408` or `429`, the API starts anyway and retries in
  the background (after 1 s, doubling up to every 30 s). Until it
  succeeds, that issuer's tokens get `503 service_unavailable` with
  `Retry-After: 5`; the other issuers are unaffected.
- **Misconfiguration fails loudly.** A discovery document that names
  another issuer or lacks a usable `jwks_uri` (or `userinfo_endpoint`
  with userinfo on), a key set that can't be parsed, or any other `4xx`
  answer fails the start with a clear error, since retrying won't help.
  Found later by the background retry (the issuer was down at startup),
  it is logged as an `ERROR` and the issuer stays unready (`503`) while
  the retry continues.
- **Stale keys keep serving.** Keys are refreshed after `jwksCacheTtl`
  seconds. If the refresh fails, Poiesis logs a `WARNING`, keeps
  validating with the cached keys and tries again after a back-off
  (1 s, doubling up to 30 s), not on every request. A failure is never
  a `500`.
- **Unknown key ids.** A token signed with a `kid` that isn't in the
  cached key set (e.g. after a Keycloak restart rotated its keys) makes
  Poiesis refetch the keys once, at most every 30 s per issuer, and
  validate again. A `kid` that is still unknown is a `401`.

## User info

![Userinfo lookup: before and after](/auth-userinfo.gif)

Some IdPs release claims (e.g. group memberships such as
`eduperson_entitlement`) at the OIDC userinfo endpoint but not in
access tokens. With `userinfo.enabled: true` on an issuer, Poiesis
calls that issuer's endpoint for every validated token and keeps the
answer on the principal, next to (not merged into) the token claims:

- The endpoint comes from the issuer's discovery document; the issuer
  is misconfigured if it has none (or announces a plain `http` endpoint
  for an `https` issuer). It can't be combined with `jwksUri`.
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
- The token is sent to its issuer's userinfo endpoint only, never to
  any other service. The owner is still taken from the token.

Where a claim is looked up by name, Poiesis takes the access token's
value first and the userinfo value only if the token lacks the claim.
If your IdP can put the claims you need into the access token, prefer
that and leave userinfo off.

## Delegation

A token may say that someone acts on the subject's behalf, with an
[RFC 8693](https://www.rfc-editor.org/rfc/rfc8693#section-4.1) `act`
claim, e.g. a workflow engine that exchanged the user's token for one
of its own:

```json
{"iss": "https://kc.example.org/realms/poiesis", "sub": "uuid-a",
 "act": {"sub": "nextflow-tower"}}
```

The subject (`sub`) stays the owner; the actor is `act.sub`, issued by
`act.iss` (default: the token's issuer). Only the first level counts;
nested `act` claims are ignored. A malformed `act` (not an object,
without a string `sub`) is a `401`.

Without a decision service, the built-in owner rule refuses delegated
tokens with `403 forbidden`: it can't tell what an actor may do. With a
decision service, the actor is sent along and the decision service
decides; see [Authorization](./authorization.md#request).

## Disabling auth

For local development and air-gapped single-tenant deployments set
`auth.enabled: false`. The API then:

- skips issuer bootstrap at startup (logs a `WARN`),
- accepts every request without a token,
- assigns each request a fixed anonymous principal,
- stamps the literal string `__anonymous__` on the `owner` column.

The downstream filter still runs — every anonymous caller shares one
bucket and sees the same tasks. Disabling auth does not "skip" the
column; it makes everyone the same owner.

## What's enforced where

| Surface          | Enforcement                                                              |
| ---------------- | ------------------------------------------------------------------------ |
| HTTP handler     | `Depends(get_principal)` on every TES route. `service-info` is unauthed. |
| Database         | `tasks.owner` stamped on every insert; reads are scoped by authz.        |
| Workers          | TaskPods and `tctl` access the DB directly without an owner filter.      |

Workers (`trec`, `tctl`) act as the system, not on behalf of any user.
They are inside the trust boundary; the API tier is where authz
applies.

## Behaviour the client sees

- **No `Authorization` header** → `401 unauthorized` with body
  `{"error":"unauthorized","message":"missing bearer token"}`.
- **Malformed or expired token, or one from an unconfigured issuer**
  → `401 unauthorized` with body
  `{"error":"unauthorized","message":"invalid token"}`. The reason
  (signature, audience, issuer, exp, …) is logged server-side at
  `WARNING` but not returned to the client.
- **Token missing a required scope** → `403 forbidden`.
- **Delegated token without a decision service** → `403 forbidden`.
- **Issuer not reachable yet, or its keys never loaded** →
  `503 service_unavailable` with `Retry-After`.
- **`GET /tasks/{id}` of a task you don't own** → `404 not found`
  (deliberate: the policy does not leak the existence of resources you
  cannot see). Same for `POST /tasks/{id}:cancel`.
- **`GET /tasks`** → returns only tasks whose `owner` is yours.

With a claim rule or a decision service, see
[Authorization](./authorization.md#behaviour-the-client-sees).

## How clients obtain a token

Out of Poiesis's scope, but the standard answers:

- **Workflow engines and CLIs**: OAuth 2.0 device flow against one of
  the configured issuers.
- **Service accounts** (CI, automated submitters): client-credentials
  grant, or the CI system's own OIDC tokens (e.g. GitHub Actions) with
  that system listed as an issuer. The token's `sub` is the
  service-account identifier, so service-account-owned tasks are
  first-class.
- **Interactive humans**: whatever your IdP's frontend uses
  (authorization code + PKCE for SPAs, etc.).

Poiesis accepts any valid token from a configured issuer. The IdPs, not
Poiesis, decide who is allowed to authenticate.

## Migrating an existing deployment

Migration `000003` renames `tasks.principal` to `tasks.owner`, adds a
`tasks.groups` column and creates the `api_keys` table. It does **not**
rewrite existing owners, since the database can't know which issuer
they came from: rows that hold a bare `sub` match nobody afterwards.
To give them back to their owners, prefix them with their issuer, once:

```sql
UPDATE tasks SET owner = '<issuer>|' || owner
WHERE owner NOT IN ('__anonymous__', '__legacy__')
  AND position('|' in owner) = 0;
```

Rows owned by `__legacy__` (created before owners were stamped) belong
to nobody and match no caller; reassign them with an `UPDATE` if
needed.

Replace `auth.oidc` in your Helm values with a one-entry
`auth.issuers` list (same keys, plus `issuer` per entry), or, without
Helm, the `POIESIS_AUTH_OIDC_*` variables with `POIESIS_AUTH_ISSUERS`.
