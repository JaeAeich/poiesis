# API keys

Workflow engines read one credential when they start and then poll
for hours or days. IdP access tokens live 5 to 60 minutes, so a long
run that was started with a token gets `401`s halfway through, even
though its tasks are fine. Poiesis API keys fix that: an owner logs in
once, mints a key for the run and gives the key to the engine.

A key is `poi_`, 43 random characters (256 bits) and a 6-character
checksum. It authenticates as the owner who minted it: the same owner
id (`namespace|subject`, see
[Owner and namespace](./authentication.md#owner-and-namespace)), so
the same tasks. Keys are the second link of the authenticator chain (see
[Authentication](./authentication.md)); the first link, for JWTs, never
looks at them.

For engine settings (Nextflow, Snakemake, cwl-tes, py-tes), see
[Workflow engines](../usage/workflow-engines.md).

![API keys: before and after, case by case](/api-keys.gif)

## Configuration

API keys are **off by default**: they are an add-on for clients that
can't refresh tokens. Turn them on, and set the limits:

```yaml
auth:
  apiKeys:
    enabled: true      # POIESIS_AUTH_API_KEYS_ENABLED (default false)
    defaultTtl: 7d     # POIESIS_AUTH_API_KEYS_DEFAULT_TTL
    maxTtl: 90d        # POIESIS_AUTH_API_KEYS_MAX_TTL
    maxPerOwner: 20    # POIESIS_AUTH_API_KEYS_MAX_PER_OWNER
```

- Lifetimes are `<n>d` (days) or `<n>h` (hours). `defaultTtl` applies
  when the minting request names none, `maxTtl` caps what it may ask
  for. Every key expires.
- `maxPerOwner` caps the **active** keys (neither revoked nor expired)
  an owner holds at once.
- Poiesis refuses to start if a lifetime is malformed or not positive,
  `defaultTtl` exceeds `maxTtl`, or `maxPerOwner` is below 1.
- API keys need `auth.enabled: true`. With `enabled: false`, the key
  routes are not mounted and keys don't authenticate.

Which tokens may **mint** keys is set per issuer, in `auth.issuers[]`:

```yaml
auth:
  issuers:
    - issuer: https://keycloak.example.org/realms/poiesis
      audience: poiesis
      keyMinting:
        clients: [poiesis-cli]  # token azp (else client_id) allowed
        maxAuthAge: 600         # optional: login at most 10 min ago
```

- An issuer without `keyMinting` can't mint keys. List the clients
  people log in with (the Swagger UI's, a CLI's), not service accounts
  or CI clients: minting turns a short-lived token into a key that
  lives for weeks, so a token stolen from a pipeline mustn't be able
  to do that.
- `maxAuthAge` also requires a recent login: the token's `auth_time`
  (when the user last authenticated) at most that many seconds ago,
  like the password prompt before creating a GitHub token. Tokens
  without `auth_time` can't mint. Keycloak puts it in access tokens
  for browser logins (authorization code, as in the Swagger UI, and
  the device flow) through its default `basic` scope, but not for the
  password grant; check what your IdP does before turning this on.

Keys live in the `api_keys` table (migration `000003`). Only the
SHA-256 of a key is stored; the key itself is shown once, when it is
minted, and can't be recovered.

## Minting a key

Minting, listing and revoking need an **OIDC access token** from one of
the configured issuers; minting also needs a token from a client in its
issuer's `keyMinting` (and a recent login with `maxAuthAge`). An API
key can't mint, list or revoke keys (a leaked key can't extend
itself), and neither can a delegated token
(one with an `act` claim). The issuer's
[claim rule](./authorization.md#claim-rule) applies as on every TES
call.

### From the Swagger UI

With `auth.swaggerUi` set, the Swagger UI at `<API URL>/docs` can log
you in at an issuer (authorization code with PKCE):

```yaml
auth:
  swaggerUi:
    issuer: https://keycloak.example.org/realms/poiesis  # one of auth.issuers
    clientId: poiesis-cli                                # a public client
    scopes: openid
```

The same as environment variables: `POIESIS_AUTH_SWAGGER_UI_ISSUER`,
`POIESIS_AUTH_SWAGGER_UI_CLIENT_ID` and `POIESIS_AUTH_SWAGGER_UI_SCOPES`.
The issuer must be one of `auth.issuers` and use OIDC discovery (not
`jwksUri`). Register the client at the IdP as a **public** client with
PKCE, the redirect URI `<API URL>/docs/oauth2-redirect` and the API's
origin as a web origin (for CORS), and make its access tokens carry
the issuer's `audience`.

Then:

1. Open `<API URL>/docs` and click **Authorize**.
2. Under `oidc`, pick the authorization code flow, keep the prefilled
   client id, tick the scopes and click **Authorize**. Log in at the
   IdP; you are sent back to the Swagger UI.
3. Run `POST /poiesis/v1/api-keys` with **Try it out**, for example
   with `{"name": "nf-run-42", "ttl": "30d"}`.
4. Copy `key` from the response. It is not shown again.

The browser talks to the IdP directly: it fetches the discovery
document, sends you to the login page and redeems the code. The IdP
must therefore be reachable from the browser under the configured
issuer URL. The login is a convenience of the documentation page
only: the token it gets is validated like any other, and the
**bearer** field next to it takes a token or a key pasted by hand.

### With curl

Any access token works, e.g. one from
[oidc-agent](https://indigo-dc.gitbook.io/oidc-agent/)
(`oidc-token <account>`) or a device flow:

```bash
TOKEN=$(oidc-token poiesis)
curl -X POST https://poiesis.example.org/poiesis/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name": "nf-run-42", "ttl": "30d", "scopes": ["tasks:read", "tasks:write"]}'
```

```json
{
  "id": "6d7eb20d-e4fd-491a-8bf3-a49e45b6b49a",
  "name": "nf-run-42",
  "key": "poi_k7H2pQ…",
  "scopes": ["tasks:read", "tasks:write"],
  "createdAt": "2026-11-21T09:00:00Z",
  "expiresAt": "2026-12-21T09:00:00Z"
}
```

The request body:

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | yes | A label, 1 to 100 characters, e.g. the run it is for. |
| `ttl` | no | Lifetime, `<n>d` or `<n>h`; default `defaultTtl`. |
| `scopes` | no | `tasks:read`, `tasks:write`; default both. |

### From a script or CLI

A CLI gets the token with the OAuth **device flow**: it prints a code
and a link, the user approves in any browser (also on another
machine, handy on HPC login nodes), and the CLI polls for the token.
Against the dev realm (`poiesis-cli` requires PKCE here too):

```bash
KC=http://keycloak.deps.svc:8080/realms/poiesis/protocol/openid-connect
VERIFIER=$(openssl rand -base64 48 | tr -d '=+/\n' | cut -c1-64)
CHALLENGE=$(printf %s "$VERIFIER" | openssl dgst -sha256 -binary \
  | openssl base64 | tr '+/' '-_' | tr -d '=')
curl -s -d client_id=poiesis-cli -d scope=openid \
  -d code_challenge="$CHALLENGE" -d code_challenge_method=S256 \
  "$KC/auth/device"
# → user_code, verification_uri_complete, device_code: open the link
curl -s -d grant_type=urn:ietf:params:oauth:grant-type:device_code \
  -d client_id=poiesis-cli -d device_code="$DEVICE_CODE" \
  -d code_verifier="$VERIFIER" "$KC/token"
# → access_token; mint with it as above
```

Device-flow tokens come from a browser login, so they carry `auth_time`
and work with `maxAuthAge`. The CLI's client id must be in the issuer's
`keyMinting.clients`. `oidc-agent` (`oidc-token <account>`) works too.

## Scopes

| Scope | Allows |
| --- | --- |
| `tasks:read` | `GetTask`, `ListTasks` |
| `tasks:write` | `CreateTask`, `CancelTask`, and everything `tasks:read` allows |

A key without the scope an operation needs gets
`403 forbidden` (`API key lacks scope tasks:write`). Scopes only limit
keys; they never widen what the owner may do, and they don't apply to
access tokens. A read-only key is useful for dashboards and monitoring
that should never submit or cancel.

## Listing and revoking

```bash
curl https://poiesis.example.org/poiesis/v1/api-keys \
  -H "Authorization: Bearer $TOKEN"
```

lists your keys, newest first, revoked and expired ones included, with
`id`, `name`, `scopes`, `createdAt`, `expiresAt`, `lastUsedAt` and
`revokedAt`; never the key. `lastUsedAt` is recorded in batches (every
minute per API replica, and at shutdown), so it may be a minute behind.

```bash
curl -X DELETE https://poiesis.example.org/poiesis/v1/api-keys/<id> \
  -H "Authorization: Bearer $TOKEN"
```

revokes a key (`204`). It stops working with the next request: keys are
looked up on every request, not cached. Revoking a revoked key is a
`204` too; a key that isn't yours, or doesn't exist, is a `404`.

Revoking every key of an owner, for an administrator, comes with the
admin role ([#123](https://github.com/jaeaeich/poiesis/issues/123)).
Until then, an operator can do it in the database:

```sql
UPDATE api_keys SET revoked_at = now()
WHERE owner = '<namespace>|<subject>' AND revoked_at IS NULL;
```

(The namespace is the issuer unless its entry sets `namespace`.)

## Sending a key

Every request carries the key in the `Authorization` header, in one of
two forms:

```text
Authorization: Bearer poi_k7H2pQ…
Authorization: Basic base64(<any user name>:poi_k7H2pQ…)
```

Bearer is the norm. Basic is for clients that only take a user name
and password: the user name is ignored, the password is the key.
Anything else (a JWT, another Basic password) is not a key and is left
to the rest of the chain.

## Deprovisioning lag

A key carries a snapshot of its owner's claims, taken from the minting
token (without `exp`, `iat`, `nbf`, `jti`, `auth_time`) and, if
[userinfo](./authentication.md#user-info) is on, the userinfo answer.
The issuer's claim rule and the decision service see the snapshot on
every request made with the key, so they decide as they would for the
owner's token at minting time.

The snapshot doesn't change afterwards. A user who leaves a group, or
is disabled at the IdP, keeps the access their keys had **until the
keys expire or are revoked**: the deprovisioning lag is the key
lifetime. Choose `maxTtl` with that in mind, and revoke keys when
offboarding users. Removing an issuer from `auth.issuers` disables all
keys of its owners at once.

## Issuers and namespaces

A key belongs to an owner, `<namespace>|<subject>`, not to an issuer
URL. On every request Poiesis looks for a configured issuer with the
key's namespace (the first one listed, if several share it): that
issuer's claim rule applies, and it is the `iss` the decision service
sees. So:

- A key keeps working when its issuer moves to a new URL, as long as
  the new entry keeps the old namespace (see
  [Issuer renames](./authentication.md#issuer-renames)).
- A key whose namespace no configured issuer has any more (the issuer
  was removed, or its namespace changed) gets `401`.

## Security model

![API keys: how they are minted and used, and what changed](/api-keys-summary.png)

What protects keys:

| Threat | Protection |
| --- | --- |
| Guessing a key | 256 random bits |
| Database leak | Only SHA-256 hashes are stored; keys are shown once |
| Leaked key | Revocation applies on the next request (no cache); every key expires (`maxTtl`) |
| Over-broad key | Scopes (`tasks:read`, `tasks:write`); `maxPerOwner` active keys |
| Key extends itself | Keys can't mint, list or revoke keys |
| Stolen token turned into a long-lived key | Only `keyMinting.clients` may mint, optionally only shortly after a login (`maxAuthAge`); delegated tokens can't |
| Distrusted issuer | Removing it from `auth.issuers` disables its keys |
| Stale claims | The decision service gets `key_age` and `snapshot_age` and may refuse old keys |
| Key committed to a repository | The `poi_` prefix and checksum let secret scanners find keys and confirm them without false positives; revoke what they find |
| Junk credentials | Malformed keys and wrong checksums get `401` without a database lookup |

What remains, and what to do about it:

- **A key is a bearer credential**: whoever holds it can use it,
  from anywhere, until it expires or is revoked. Serve Poiesis over
  TLS only, keep keys in the engine's secret store or environment (see
  [Workflow engines](../usage/workflow-engines.md)), not in committed
  configuration, and mint short-lived keys for one-off runs.
- **Deprovisioning lag**: see below.
- **Request floods**: a well-formed key with a valid checksum costs one
  indexed lookup. Rate-limit at the ingress or gateway.

To scan for leaked keys, match `poi_[A-Za-z0-9_-]{43}[0-9A-Za-z]{6}`;
the last 6 characters are the base62 CRC32 of the 43 before them.

Every mint and revocation is logged at `INFO` with the key id, owner
and (for mints) client, scopes and expiry; refused mints at `WARNING`.

## Behaviour the client sees

| Situation | Result |
| --- | --- |
| Unknown, malformed, revoked or expired key | `401`, `invalid token` |
| Key of a namespace no issuer in `auth.issuers` has (any more) | `401`, `invalid token` |
| Database unreachable while checking a key | `503`, `Retry-After: 5` |
| Key lacks the operation's scope | `403` |
| Minting, listing or revoking with a key or a delegated token | `403` |
| Minting with a token of an issuer without `keyMinting`, a client not listed, or (with `maxAuthAge`) an old or missing `auth_time` | `403` |
| `ttl` above `maxTtl` | `400` |
| Malformed body (`name`, `ttl`, unknown scope) | `422` |
| `maxPerOwner` active keys already | `409`, revoke one first |
| Revoking someone else's or a missing key | `404` |

What a key can do beyond its scopes is decided as for its owner: the
built-in owner rule, or the decision service, which learns that the
request came with a key from `subject.properties.via` (`apikey`) and
`credential_id` (the key id); see
[Authorization](./authorization.md#request).
