---
description: How Poiesis validates bearer tokens from trusted issuers - configuration, audience, token type, owners, outages, userinfo, delegation and RFC 9728 discovery.
---

# Authentication

Poiesis is a **resource server**: it validates signed bearer tokens
(JWTs) minted by one or more trusted issuers (Keycloak, Auth0, Dex,
Cognito, GitHub Actions OIDC, a gateway, …) and rejects anything else
with `401`. It does not run a login flow, issue tokens, or store
passwords. Clients obtain a token from an issuer and present it as
`Authorization: Bearer <jwt>` on every request.

Each request goes through an **authenticator chain**, in order:

1. **JWT**: a bearer token with three dot-separated parts, validated
   against the issuer it names (this page).
2. **API key**: a Poiesis key (`poi_…`) as a bearer token or a Basic
   password, minted by an owner with a token, for clients that outlive
   one, such as workflow engines. See [API keys](./api-keys.md).

The first link that recognises the credential decides: it returns the
caller, or refuses (`401`, `403` for a missing required scope, or `503`
if it can't check right now). A
credential no link recognises, or none at all, is a `401`.

By default, authorization is an **owner-only rule**: every task row
carries an `owner` column, and callers see and cancel only the rows
whose `owner` is their own. An optional claim rule per issuer and an
external decision service can restrict that further; only with
sharing turned on can a decision service show a task to anyone but
its owner. See [Authorization](./authorization.md).

<FlowDiagram :spec="{
  title: 'The authenticator chain',
  h: 230,
  nodes: {
    rq: { x: 4, y: 88, w: 104, label: 'Request', sub: 'Authorization' },
    jwt: { x: 154, y: 20, w: 118, label: 'JWT link', sub: 'iss matches' },
    key: { x: 154, y: 88, w: 118, label: 'API key link', sub: 'poi_...' },
    no: { x: 154, y: 160, w: 118, label: '401', sub: 'nobody claims it' },
    ow: { x: 316, y: 88, w: 100, label: 'Caller', sub: 'issuer|sub' }
  },
  edges: [['rq','jwt'],['rq','key'],['rq','no'],['jwt','ow'],['key','ow']],
  hops: [
    { f: 'rq', t: 'jwt', label: 'eyJ...', cap: 'A JWT goes to the issuer named in its iss claim, matched exactly.' },
    { f: 'jwt', t: 'ow', label: 'alice', tone: 'ok', cap: 'Signature, audience, token type and client pass: the caller is issuer|alice.' },
    { f: 'rq', t: 'key', label: 'poi_7Kq', cap: 'An API key, as Bearer or as a Basic password, is looked up by its hash.' },
    { f: 'key', t: 'ow', label: 'alice', tone: 'ok', cap: 'It acts as the owner who minted it.' },
    { f: 'rq', t: 'no', label: 'none', tone: 'bad', cap: 'No credential, or one no link recognises: 401 with WWW-Authenticate.' }
  ]
}" />

## Configuration

The Helm chart lists the trusted issuers under `auth.issuers`. The
list reaches the API pod as one environment variable,
`POIESIS_AUTH_ISSUERS`, a JSON array with the same (camelCase) keys.

```yaml
auth:
  enabled: true
  resource: https://poiesis.example.org # public URL, see "Discovery" below
  issuers:
    - issuer:          https://keycloak.example.org/realms/poiesis
      audience:        poiesis # or a list, see "Audience" below
      tokenTypes:      [JWT]   # default [at+jwt], see "Token type" below
      clients:         [poiesis-cli, portal] # optional, see "Clients"
    # namespace:       kc      # optional, see "Owner and namespace"
      principalClaim:  sub     # see "Owner and namespace" below
      requiredScopes:  []      # optional: reject tokens missing these
      requiredClaim:           # optional admission rule, see Authorization
        name:          groups
        values:        [/poiesis-users]
      admin:                   # optional built-in admins, see Authorization
        name:          groups
        values:        [/poiesis-admins]
      actors:          []      # optional, see "Delegation" below
      userinfo:
        enabled:       false   # see "User info" below
      jwksCacheTtl:    3600    # seconds to cache the issuer's keys
      clockSkew:       30      # seconds of leeway on exp / nbf / iat
      timeout:         10      # seconds per call to the issuer
      keyMinting:              # optional, see API keys
        clients:       [poiesis-cli]
      serviceClients: []       # optional, see "Service clients" below
    # A gateway (Envoy, Istio, oauth2-proxy) that signs its own JWTs
    # and publishes only its keys: no discovery, no userinfo.
    - issuer:          https://gateway.example.org
      audience:        poiesis
      tokenTypes:      [JWT]   # the typ its JWTs carry
      jwksUri:         http://gateway.mesh.svc/.well-known/jwks.json
```

The same configuration as environment variables:

```bash
POIESIS_AUTH_ENABLED=true
POIESIS_AUTH_RESOURCE=https://poiesis.example.org
POIESIS_AUTH_ISSUERS='[
  {"issuer": "https://keycloak.example.org/realms/poiesis", "audience": "poiesis",
   "tokenTypes": ["JWT"], "clients": ["poiesis-cli", "portal"],
   "requiredClaim": {"name": "groups", "values": ["/poiesis-users"]},
   "keyMinting": {"clients": ["poiesis-cli"]}},
  {"issuer": "https://gateway.example.org", "audience": "poiesis",
   "tokenTypes": ["JWT"],
   "jwksUri": "http://gateway.mesh.svc/.well-known/jwks.json"}
]'
```

| Key | Default | Meaning |
| --- | --- | --- |
| `issuer` | required | Exact `iss` of the tokens; the discovery base URL. |
| `audience` | required | Accepted `aud`: a string or a list; see [Audience](#audience). |
| `tokenTypes` | `[at+jwt]` | Accepted header `typ` values; `[]` turns the check off. See [Token type](#token-type). |
| `clients` | any | Accepted clients (`azp`, else `client_id`). See [Clients](#clients). |
| `namespace` | the issuer | Prefix of the owner id. See [Owner and namespace](#owner-and-namespace). |
| `principalClaim` | `sub` | Claim naming the subject; dotted paths walk nested objects. |
| `requiredScopes` | none | Scopes every token must carry, else `403`. |
| `requiredClaim` | none | Admission rule for this issuer's callers; see [Authorization](./authorization.md#claim-rule). |
| `admin` | none | Built-in admins of this issuer, without a decision service; see [Authorization](./authorization.md#admin). |
| `actors` | none | Actors the built-in policy accepts; see [Delegation](#delegation). |
| `userinfo.enabled` | `false` | Fetch userinfo per token; see [User info](#user-info). |
| `jwksUri` | discovery | Static key set URL; skips discovery. |
| `jwksCacheTtl` | `3600` | Seconds to cache the keys. |
| `clockSkew` | `30` | Seconds of leeway on `exp` / `nbf` / `iat`. |
| `timeout` | `10` | Seconds per call to the issuer. |
| `keyMinting` | none | Which tokens may mint API keys; see [API keys](./api-keys.md#configuration). |
| `serviceClients` | none | Client-credentials clients with their own audience; see [Service clients](#service-clients). |

Each entry needs `issuer` and `audience`; everything else has the
defaults shown. Poiesis refuses to start (and the chart's JSON schema
refuses to install) when auth is enabled with no issuer, an entry lacks
`issuer` or `audience`, an entry has an
unknown key, an empty value in a list (`audience`, `tokenTypes`,
`clients`, `actors`, `requiredScopes`), an empty `clients` list, a
`namespace` that is empty or contains `|`, an incomplete
`requiredClaim` or `admin`, a `serviceClients` entry without
`clientId` or `audience` (or with an empty or blank one), or `userinfo`
combined with `jwksUri`; an issuer listed twice, or a service client
listed twice for one issuer, refuses to start (the schema can't see
that). The old
`auth.oidc.*` values and `POIESIS_AUTH_OIDC_*` variables are gone: any
`POIESIS_AUTH_OIDC_*` variable left in the environment refuses to start,
naming `POIESIS_AUTH_ISSUERS` as its replacement.

API keys (`auth.apiKeys`) and the Swagger UI login (`auth.swaggerUi`)
are set next to the issuers; see [API keys](./api-keys.md).

There is no `clientSecret` — Poiesis is a resource server, not an OAuth
client, and never talks to a token endpoint. Its only network calls for
authentication go to the configured issuers: an anonymous GET of the discovery document
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
issuer: signature (RS, ES or PS algorithms), `iss`, `aud` (one of the
issuer's `audience`, or of a [service client](#service-clients)'s own),
`exp` (required), `nbf` and `iat` (when present),
all three with `clockSkew` of leeway, the header
`typ` (`tokenTypes`), the client (`clients`, if set) and the issuer's
`requiredScopes`.

The discovery document's own `issuer` must equal the configured
`issuer` exactly; otherwise the issuer is misconfigured (see below).
The `jwks_uri` and `userinfo_endpoint` it announces must be absolute
`https` URLs (`http` only if the issuer is `http` too).

Identity only ever comes from a token Poiesis verifies itself. Plain
headers such as `X-User`, `X-Forwarded-User` or `Remote-User` are
ignored, also behind a proxy: a gateway that authenticates users in its
own way (SAML, LDAP, mTLS) must sign a JWT for Poiesis and be listed as
an issuer, usually with `jwksUri`.

## Audience

A token passes if its `aud` (a string or a list) holds one of the
issuer's `audience` values. Give each Poiesis instance an audience of
its own, so that a token issued for another service (a gateway, a
portal, another TES) is refused here: that is what makes forwarding or
exchanging tokens per hop (RFC 8693) safe. Several values are meant for
migrations, e.g. while moving from a shared audience to a per-instance
one:

```yaml
    - issuer: https://login.example.org
      audience: [poiesis-node-1, poiesis]  # drop `poiesis` once moved
```

A plain string is one value, as before.

### Shared audience

Federations often can't mint a token per service: LS Login, for
example, puts the requesting client's id into `aud`, so a portal's
users arrive with the portal's client id as audience, and every
service behind that portal accepts the same token. Poiesis supports
this (list that client id in `audience`), but know the risk: **any
service that receives such a token can replay it** against every
other service that accepts the audience, this Poiesis included.
Mitigate it with:

- [`clients`](#clients), to accept only tokens obtained by the
  clients you expect (this narrows who can call, but doesn't stop the
  replay of those clients' tokens);
- short access-token lifetimes at the IdP;
- token exchange (RFC 8693) per hop, once the IdP and your gateway
  support it, moving to a per-instance audience.

See [OIDC federations](../guides/oidc-federations.md) for a full
LS Login entry.

## Token type

Many IdPs sign several kinds of JWT with the same keys: access tokens,
ID tokens, logout tokens. Only access tokens may call Poiesis.
[RFC 9068](https://www.rfc-editor.org/rfc/rfc9068#section-2.1) access
tokens say so in their header, `typ: at+jwt`, and by default
(`tokenTypes: [at+jwt]`) Poiesis accepts no other `typ`. This matters
most where `audience` is a client id: an ID token of that client has
the same `aud`.

- Values compare without regard to case, and `application/` is
  optional (RFC 7515), so `at+jwt` and `application/at+jwt` are the
  same.
- A token without `typ` fails any non-empty list.
- A refused `typ` is a `401` (`invalid token`), logged at `WARNING`
  with the issuer, the `typ` seen and the setting to change.
- **Keycloak** puts `typ: JWT` in the header of its access tokens, so
  list `tokenTypes: [JWT]` for it (the dev manifest does). It puts the
  same `typ` on its ID tokens, so for Keycloak the check doesn't tell
  them apart: keep `audience` different from every client id (its ID
  tokens carry the client id as `aud`).
- `tokenTypes: []` turns the check off, for IdPs that type their tokens
  inconsistently. That is weaker: then any JWT of the issuer with the
  audience passes, so make sure only access tokens carry it.

## Clients

`clients` optionally lists the OAuth clients whose tokens are accepted:
the token's `azp` (OIDC), else its `client_id` (RFC 9068), must be one
of them. Tokens of other clients, and tokens with neither claim, get a
`401` (`invalid token`). Use it when other clients of the issuer can
obtain tokens with your audience; leave it out to accept any client.

```yaml
    - issuer: https://keycloak.example.org/realms/poiesis
      audience: poiesis
      clients: [poiesis-cli, portal, poiesis-ci]
```

It is independent of `keyMinting.clients`, which only says which of the
accepted clients may [mint API keys](./api-keys.md#configuration).
[Service clients](#service-clients) are listed on their own and need no
entry here.

## Service clients

Some callers have no user behind them: a smoke test, a CI pipeline, a
monitoring probe that gets its own short-lived tokens with the OAuth
client credentials grant. Such tokens carry the client ID as `sub` (and
as `azp` or `client_id`) and none of a user's claims, so an issuer whose
users need [userinfo](#user-info) and a
[`requiredClaim`](./authorization.md#claim-rule) would refuse them.
`serviceClients` admits them without weakening the rules for the users:

```yaml
    - issuer: https://login.aai.lifescience-ri.eu/oidc/
      audience: [<user-facing audience>]
      userinfo: {enabled: true}
      requiredClaim: {name: eduperson_entitlement, values: [...]}
      serviceClients:
        - clientId: <client ID>
          audience: [<audience of the client's tokens>]  # or a string
```

A token is a service client's if, after the signature, `iss`, `exp`
and `tokenTypes` checks, its client (`azp`, else `client_id`) **and**
its `sub` both equal a listed `clientId`. Then:

- its `aud` must hold one of that entry's `audience` values; the
  issuer's `audience` doesn't count for it, and the entry's doesn't
  count for user tokens;
- it is never looked up at userinfo, and the issuer's `requiredClaim`
  and `clients` don't apply to it; `tokenTypes`, `requiredScopes` and
  the delegation (`act`) rules still do;
- it is never a built-in [admin](./authorization.md#admin) and can't
  [mint API keys](./api-keys.md#configuration), whatever `admin` and
  `keyMinting` say;
- its owner is `<namespace>|<subject>` as for anyone (with the default
  `principalClaim: sub`, `<namespace>|<client ID>`), so without a
  decision service it sees and cancels only its own tasks;
- with a [decision service](./authorization.md#decision-service), every
  request is asked as for any other caller (the client ID is in
  `subject.properties.sub` and `client_id`), and its answer applies:
  what a service client may do is policy.

User tokens carry the user's `sub`, never the client's, so no user
token can match, not even one obtained through the listed client: such
a token is judged as a user's, with the issuer's `audience`, userinfo
and `requiredClaim`. Without `serviceClients`, nothing changes. Check
what the IdP puts in `aud` of the client's tokens before listing it:
a token without `aud` is refused.

## Owner and namespace

The owner stamped on every task (and API key) is the opaque string
`<namespace>|<subject>`. `<subject>` is the value of the issuer's
`principalClaim` (default `sub`); `<namespace>` is the issuer's
`namespace`, which defaults to the issuer itself. Two issuers that issue
the same `sub` therefore never share tasks:

| Caller | Issuer | `sub` | Owner |
| --- | --- | --- | --- |
| Alice | `https://kc.example.org/realms/poiesis` | `uuid-a` | `https://kc.example.org/realms/poiesis\|uuid-a` |
| CI | `https://token.actions.githubusercontent.com` | `repo:org/x:ref:refs/heads/main` | `https://token.actions.githubusercontent.com\|repo:org/x:ref:refs/heads/main` |
| Bob, with `namespace: ls-login` | `https://login.example.org` | `uuid-b` | `ls-login\|uuid-b` |

A `namespace` must not be empty or contain `|`. Changing it (or the
issuer URL, while it is the default) changes the owner of every caller
of the issuer, so set it before the first tasks are created, or only
for a rename (below).

### Issuer renames

When an IdP moves to a new URL, its tokens carry the new `iss`, and
with the default namespace their owners change: the callers no longer
see their tasks, and their API keys stop working. Give the new entry
the old URL as `namespace` instead, so owners stay the same, with no
data migration (as long as the IdP keeps its users' `sub` values
across the move):

```yaml
auth:
  issuers:
    - issuer: https://kc.example.org/realms/poiesis       # old URL
      audience: poiesis
    - issuer: https://login.example.org/realms/poiesis    # new URL
      audience: poiesis
      namespace: https://kc.example.org/realms/poiesis
```

Keep the old entry while tokens of the old URL are still in use, then
remove it; the namespace of the new entry stays. Issuers may share a
namespace on purpose, but equal subjects of such issuers are then one
owner, so Poiesis logs a `WARNING` at startup naming every set of
issuers that share one. Never share a namespace between two different
IdPs.

### Principal claim

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

#### Worked example

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
`403 forbidden` with
`WWW-Authenticate: Bearer error="insufficient_scope", scope="…"`
(RFC 6750 §3.1) naming all the issuer's required scopes, plus
`resource_metadata` when [`auth.resource`](#discovery) is set, so a
client can get a new token with them. Scopes are therefore scope tokens
(RFC 6749 §3.3): no spaces, quotes or backslashes. This is
intentionally coarse — TES is a small API surface and per-endpoint
scopes were deferred to a later iteration. Leave the list empty
(default) to skip the check.

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

Some IdPs release claims (e.g. group memberships such as
`eduperson_entitlement`) at the OIDC userinfo endpoint but not in
access tokens. With `userinfo.enabled: true` on an issuer, Poiesis
calls that issuer's endpoint for every validated token (except those of
[service clients](#service-clients)) and keeps the
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
- With [API keys](./api-keys.md#deprovisioning-lag), the userinfo
  answer at minting time is frozen in the key's snapshot: group
  changes at the IdP reach keys only when they are re-minted.
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

### Trusted actors

Once an IdP issues `act` on exchanged tokens, a deployment behind a
gateway (e.g. proTES) without a decision service would refuse every
call. `actors` lists the actors whose delegated tokens of this issuer
the built-in owner rule accepts anyway, typically the gateway's client
id:

```yaml
    - issuer: https://login.example.org
      audience: poiesis-node-1
      actors: [protes-gateway]
```

A delegated token passes if its `act.sub` is listed and its `act.iss`
(default: the token's issuer) is the token's issuer: an actor id of
another issuer may name someone else. The actor then acts as the
subject, with the subject's tasks and nothing more. Any other delegated
token still gets `403`. With a decision service, `actors` has no effect:
the decision service decides about every actor, listed or not.

## Disabling auth

For local development and air-gapped single-tenant deployments set
`auth.enabled: false`. The API then:

- skips issuer bootstrap at startup (logs a `WARNING`),
- accepts every request without a token,
- assigns each request a fixed anonymous principal,
- stamps the literal string `__anonymous__` on the `owner` column.

The downstream filter still runs — every anonymous caller shares one
bucket and sees the same tasks. Disabling auth does not "skip" the
column; it makes everyone the same owner.

## What's enforced where

| Surface          | Enforcement                                                              |
| ---------------- | ------------------------------------------------------------------------ |
| HTTP handler     | `Depends(get_principal)` on every TES and API key route. `service-info`, the probes (`/healthz`, `/readyz`, `/startupz`) and the resource metadata are unauthed. |
| Database         | `tasks.owner` stamped on every insert; reads are scoped by authz.        |
| Workers          | TaskPods and `tctl` access the DB directly without an owner filter.      |

Workers (`trec`, `tctl`) act as the system, not on behalf of any user.
They are inside the trust boundary; the API tier is where authz
applies.

## Behaviour the client sees

- **No `Authorization` header** → `401 unauthorized` with body
  `{"error":"unauthorized","message":"missing bearer token"}` and
  `WWW-Authenticate: Bearer resource_metadata="…"` (see
  [Discovery](#discovery)).
- **Malformed or expired token, one from an unconfigured issuer, of
  another audience, a token type not in `tokenTypes` or a client not
  in `clients`** → `401 unauthorized` with body
  `{"error":"unauthorized","message":"invalid token"}` and
  `WWW-Authenticate: Bearer error="invalid_token", resource_metadata="…"`. The reason
  (signature, audience, issuer, exp, `typ`, client, …) is logged
  server-side at `WARNING` but not returned to the client.
- **Token missing a required scope** → `403 forbidden` with
  `WWW-Authenticate: Bearer error="insufficient_scope", scope="…", resource_metadata="…"`
  (see [Required scopes](#required-scopes)). Other `403`s carry no
  challenge: a new token wouldn't change their answer.
- **Delegated token without a decision service**, unless its actor is
  in the issuer's `actors` → `403 forbidden`.
- **Issuer not reachable yet, or its keys never loaded** →
  `503 service_unavailable` with `Retry-After`.
- **`GET /tasks/{id}` of a task you don't own** → `404 not found`
  (deliberate: the policy does not leak the existence of resources you
  cannot see). Same for `POST /tasks/{id}:cancel`.
- **`GET /tasks`** → returns only tasks whose `owner` is yours.

API keys behave the same, plus their own cases (revoked, expired, a
missing scope); see [API keys](./api-keys.md#behaviour-the-client-sees).
With a claim rule or a decision service, see
[Authorization](./authorization.md#behaviour-the-client-sees).

## Discovery

A client that knows only the URL of a Poiesis can find out where to
get a token. With `auth.resource` (`POIESIS_AUTH_RESOURCE`) set to the
public URL, Poiesis serves **OAuth 2.0 Protected Resource Metadata**
([RFC 9728](https://www.rfc-editor.org/rfc/rfc9728)), and every `401`
(and a `403` for a missing scope) points to it:

<FlowDiagram :spec="{ title: 'Discovering the issuer', h: 230,
  nodes: { c: { x: 10, y: 92, w: 100, label: 'Client', sub: 'knows the URL' }, api: { x: 300, y: 92, w: 110, label: 'Poiesis' },
           md: { x: 155, y: 16, w: 110, label: 'Metadata', sub: 'RFC 9728' }, iss: { x: 155, y: 170, w: 110, label: 'Issuer', sub: 'OIDC' } },
  edges: [['c','api'], ['c','md'], ['c','iss']],
  hops: [ { f: 'c', t: 'api', label: 'GET /tasks', cap: 'A client calls Poiesis with no token.' },
          { f: 'api', t: 'c', label: '401', tone: 'bad', cap: 'The 401 names the metadata URL in WWW-Authenticate.' },
          { f: 'c', t: 'md', label: 'GET', cap: 'The metadata lists the issuers it can log in at.' },
          { f: 'c', t: 'iss', label: 'log in', cap: 'The client gets a token from that issuer.' },
          { f: 'c', t: 'api', label: 'Bearer …', tone: 'ok', cap: 'It retries with the token.' } ] }" />

```console
$ curl -i https://poiesis.example.org/ga4gh/tes/v1/tasks
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer resource_metadata="https://poiesis.example.org/.well-known/oauth-protected-resource"

$ curl https://poiesis.example.org/.well-known/oauth-protected-resource
{
  "resource": "https://poiesis.example.org",
  "authorization_servers": ["https://keycloak.example.org/realms/poiesis"],
  "bearer_methods_supported": ["header"],
  "resource_name": "Poiesis",
  "resource_documentation": "https://poiesis.jaeaeich.com"
}
```

From there the client reads the issuer's own metadata
(`<issuer>/.well-known/openid-configuration`) for its device or
authorization endpoint, and logs in. The same pattern serves MCP
servers, so generic OAuth clients and SDKs already follow it.

| Field | From |
| --- | --- |
| `resource` | `auth.resource`, without a trailing `/`. Clients check that it equals the URL they asked. |
| `authorization_servers` | The issuers, except those with `jwksUri` (gateways publish only keys, clients can't log in there). |
| `scopes_supported` | The issuers' `requiredScopes`, if any. |
| `bearer_methods_supported` | `header`: tokens and API keys go in `Authorization`. |
| `resource_name`, `resource_documentation` | The service-info `name` and `documentationUrl` (`serviceInfo.*`), with the same defaults. |

Set `resource` to the URL clients use, scheme included: behind a TLS
ingress, `https://…`, though Poiesis itself sees plain HTTP. Poiesis
never derives it from the request's `Host`. With a path
(`https://example.org/poiesis`), the metadata is at
`https://example.org/.well-known/oauth-protected-resource/poiesis`
(RFC 9728 §3.1): route that path to the API as well. Unset, nothing is
served and a `401` carries a plain `WWW-Authenticate: Bearer` (with
`error="invalid_token"` for a bad credential), as RFC 6750 asks.

The metadata names no audience: issuers set it (Keycloak with an
audience mapper), or, with
[resource indicators (RFC 8707)](https://www.rfc-editor.org/rfc/rfc8707),
the client asks for `resource`; then list that URL in `audience`.

## How clients obtain a token

Out of Poiesis's scope, but the standard answers:

- **Workflow engines**: an [API key](./api-keys.md), minted once with
  a token; engines read their credential once, and runs outlive tokens.
  See [Workflow engines](../guides/workflow-engines.md).
- **CLIs and scripts**: OAuth 2.0 device flow against one of the
  configured issuers, or a token from
  [oidc-agent](https://indigo-dc.gitbook.io/oidc-agent/).
- **Service accounts** (CI, automated submitters): client-credentials
  grant, or the CI system's own OIDC tokens (e.g. GitHub Actions) with
  that system listed as an issuer. The token's `sub` is the
  service-account identifier, so service-account-owned tasks are
  first-class.
- **Interactive humans**: whatever your IdP's frontend uses
  (authorization code + PKCE for SPAs, etc.). The Swagger UI at
  `/docs` can log in this way to mint API keys; see
  [From the Swagger UI](./api-keys.md#from-the-swagger-ui).
  For a Keycloak setup, see the [Keycloak guide](../guides/keycloak.md).

Poiesis accepts any valid token from a configured issuer. The IdPs, not
Poiesis, decide who is allowed to authenticate.

## Migrating an existing deployment

What changes for a deployment that ran with `auth.oidc`:

Migration `000003` renames `tasks.principal` to `tasks.owner`, adds a
`tasks.groups` column and creates the `api_keys` table. It does **not**
rewrite existing owners, since the database can't know which issuer
they came from: rows that hold a bare `sub` match nobody afterwards.
To give them back to their owners, prefix them with their issuer (or
the issuer's `namespace`, if you set one), once:

```sql
UPDATE tasks SET owner = '<namespace>|' || owner
WHERE owner NOT IN ('__anonymous__', '__legacy__')
  AND position('|' in owner) = 0;
```

Rows owned by `__legacy__` (created before owners were stamped) belong
to nobody and match no caller; reassign them with an `UPDATE` if
needed.

Replace `auth.oidc` in your Helm values with a one-entry
`auth.issuers` list (the same keys, as one list entry), or, without
Helm, the `POIESIS_AUTH_OIDC_*` variables with `POIESIS_AUTH_ISSUERS`.

### Upgrading to issuer hardening

Existing owners keep working: the default `namespace` is the issuer,
as before, and `clients` and `actors` are off until set. Two changes
need attention:

- **Token type.** Tokens must now carry `typ: at+jwt` in the header by
  default. If your IdP types its access tokens otherwise (Keycloak:
  `JWT`), set `tokenTypes` for it, or every request gets `401` (the
  `WARNING` in the log names the `typ` seen).
- **Claim rule.** The global `authz.requiredClaim` is gone: it matched
  the claim value whichever issuer the token came from. Move it to the
  issuer it is meant for, as `auth.issuers[].requiredClaim`. The chart
  refuses to render while `authz.requiredClaim` is set, and the API
  refuses to start while any `POIESIS_AUTHZ_REQUIRED_CLAIM_*` variable
  is set.
