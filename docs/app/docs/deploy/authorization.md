# Authorization

Poiesis decides who may do what to which task in three layers, each
optional except the first:

1. **Authentication** ([Authentication](./authentication.md)): a valid
   token of a configured issuer (audience, `requiredScopes`), optionally
   enriched with userinfo, or an [API key](./api-keys.md) minted with
   one, limited to its scopes (`tasks:read`, `tasks:write`). Poiesis
   stamps the caller's owner id (`namespace|subject`) on every task it
   creates.
2. **Claim rule** (`auth.issuers[].requiredClaim`): an admission gate
   per issuer, "who of this issuer may use this service at all",
   checked on every TES call and on minting, listing and revoking API
   keys (which the decision service is not asked about: callers only
   ever manage their own keys).
3. **Decision** (`authz.decisionService`): "what may this caller do".
   Without a decision service, the built-in owner rule applies: anyone
   admitted may create tasks and sees and cancels only their own, and
   delegated tokens (with an `act` claim) are refused unless their actor
   is listed in the issuer's
   [`actors`](./authentication.md#trusted-actors).

When both the rule and the decision service are set, **both must
allow**. Everything else (entitlements, roles, admin rights, image or
resource limits, GA4GH Passport visas) belongs in the decision service,
not in Poiesis. Both need `auth.enabled: true`; Poiesis refuses to
start otherwise.

![Authorization: before and after](/authz.gif)

## Configuration

The decision service's Helm values map 1:1 to
`POIESIS_AUTHZ_DECISION_SERVICE_*` environment variables (lists are
JSON arrays, since values such as group URNs may contain commas). Claim
rules are set per issuer, in `auth.issuers[]` (`POIESIS_AUTH_ISSUERS`).

```yaml
auth:
  issuers:
    - issuer: https://login.aai.lifescience-ri.eu/oidc/
      audience: poiesis
      requiredClaim:     # optional, per issuer; see "Claim rule" below
        name: eduperson_entitlement
        values: ["…"]    # and/or prefixes: ["…"]
authz:
  decisionService:
    url: ""           # POIESIS_AUTHZ_DECISION_SERVICE_URL; empty = owner rule
    timeout: 2        # POIESIS_AUTHZ_DECISION_SERVICE_TIMEOUT (seconds)
    claims: []        # POIESIS_AUTHZ_DECISION_SERVICE_CLAIMS
    credentialFile: "" # POIESIS_AUTHZ_DECISION_SERVICE_CREDENTIAL_FILE
```

## Claim rule

An issuer's `requiredClaim` applies to that issuer's callers only:
its tokens, and API keys minted with them (judged on the key's claims
snapshot). An issuer without one admits all its callers. Rules match
(`iss`, claim, value), never the value alone: with several issuers,
another IdP (a partner Keycloak, a gateway) that puts the same value
into its tokens is still judged by its own rule.

The rule looks up the claim `name`: the exact name first (so URI-named
claims such as `https://example.org/groups` work), then as a dotted
path (`realm_access.roles`); in the access token first, then in
userinfo if [userinfo](./authentication.md#user-info) is on. The caller
is admitted if the claim is a string or a list of strings with a value
that equals one of `values` or starts with one of `prefixes`. A missing
claim or another type is a `403`, before any decision service call.
Poiesis refuses to start (and the chart's schema refuses to install)
with a rule without a name, without values or prefixes, or with an
empty value or prefix.

Prefixes are compared as raw strings, so include the delimiter. For
LS Login groups, admit a group and its subgroups with the group as an
exact value and its subgroup prefix ending in `:`:

```yaml
auth:
  issuers:
    - issuer: https://login.aai.lifescience-ri.eu/oidc/
      audience: poiesis
      requiredClaim:
        name: eduperson_entitlement
        values:
          - "urn:geant:lifescience-ri.eu:group:example-vo#login.aai.lifescience-ri.eu"
        prefixes:
          - "urn:geant:lifescience-ri.eu:group:example-vo:"
```

Without the trailing `:`, the prefix would also admit
`…:group:example-vo2#…`.

Every caller of the issuer needs the claim, including its service
clients (client-credentials tokens) and callers behind a gateway such
as proTES, which Poiesis sees as the caller. Their tokens usually carry
no user entitlements, so they get `403`. For such deployments, leave
the rule unset and express "entitled users or client X" in the decision
service (e.g. by `subject.properties.client_id`), or give the gateway
an issuer entry of its own.

The global `authz.requiredClaim` of earlier versions matched the value
whichever issuer the token came from, and is refused: the chart fails
to render while it is set, and the API refuses to start while any
`POIESIS_AUTHZ_REQUIRED_CLAIM_*` variable is set, naming
`auth.issuers[].requiredClaim` as the replacement.

## Decision service

Any service implementing the
[OpenID AuthZEN 1.0](https://openid.net/specs/authorization-api-1_0-final.html)
Access Evaluation API works, directly (e.g. OpenFGA's experimental
AuthZEN endpoint) or through a thin adapter (e.g. in front of OPA).
`url` is the full evaluation URL, e.g.
`http://localhost:8181/access/v1/evaluation` for a sidecar.

Poiesis asks one question per decision (`POST`, one attempt, no
retries) and allows only on `200` with `{"decision": true}`.

### Request

```json
{
  "subject": {
    "type": "user",
    "id": "<owner id: namespace|subject, as stamped on tasks>",
    "properties": {
      "iss": "...", "sub": "...", "client_id": "...", "scope": ["..."],
      "via": "oidc", "credential_id": "...",
      "actor": {"iss": "...", "sub": "..."},
      "claims": {"eduperson_entitlement": ["..."]}
    }
  },
  "action": {"name": "GetTask", "properties": {"view": "BASIC"}},
  "resource": {
    "type": "tes_task", "id": "<task id>",
    "properties": {"owner": "...", "state": "RUNNING", "tags": {}}
  },
  "context": {"tes": {"profile": "tes-authzen/1", "service_id": "org.ga4gh.poiesis"}}
}
```

- `subject` comes from the validated token and userinfo only, never
  from request headers or the body. `iss` is the token's (configured)
  issuer and `sub` its `sub` claim. `client_id` is the token's `azp`
  or `client_id`. `claims` holds only the claims listed in
  `decisionService.claims`, looked up like the claim rule's. **The
  access token is never sent.**
- `subject.id` and `resource.properties.owner` are **opaque owner
  ids**, today `<namespace>|<subject>` (the namespace being the
  issuer's `namespace`, the issuer by default, and the subject its
  `principalClaim`, `sub` by default). Compare them with each other,
  but don't parse them: their format may change, and issuers may share
  a namespace (see
  [Issuer renames](./authentication.md#issuer-renames)). Use
  `subject.properties.iss` and `sub` for identity-based rules; `iss`
  is always the token's issuer.
- `subject.properties.via` names how the caller authenticated: `oidc`
  for an access token, `apikey` for an [API key](./api-keys.md).
  `credential_id` identifies the credential when there is one: the
  token's `jti`, or the key's id. For a key, `key_age` and
  `snapshot_age` give the seconds since it was minted (the snapshot is
  taken then), so a policy can refuse old keys or stale claims. For a
  key, `iss`, `sub`, `client_id`
  and `claims` come from the snapshot of the minting token (see
  [Deprovisioning lag](./api-keys.md#deprovisioning-lag)), so a
  policy written for tokens applies to keys unchanged; `scope` is the
  key's own (`tasks:read`, `tasks:write`). Use `via` to treat keys
  differently. Both fields were added to the
  `tes-authzen/1` profile without changing its name: a service that
  ignores unknown properties is unaffected.
- `subject.properties.actor` is present only for a delegated token: the
  RFC 8693 `act` claim's `sub` and `iss` (default: the token's issuer).
  The subject is still the owner; your policy decides what the actor
  may do on the subject's behalf (see
  [Delegation](./authentication.md#delegation)). The issuer's `actors`
  list is not sent and doesn't bind the decision service: it only
  widens the built-in owner rule.
- `action.name` is the TES `operationId`:

  | Action       | Resource                                  | Result of a deny |
  | ------------ | ----------------------------------------- | ---------------- |
  | `CreateTask` | `tes_task_set` `own`, with `task` (below) | `403`            |
  | `GetTask`    | `tes_task` with `owner`, `state`, `tags`  | `404`            |
  | `CancelTask` | `tes_task` with `owner`, `state`, `tags`  | `403` if `GetTask` is allowed, else `404` |
  | `ListTasks`  | `tes_task_set` `all` and `own`            | `403` if both are denied |

  `GetTask` and `ListTasks` carry `action.properties.view`.
- For a missing task, Poiesis still asks, with empty properties, and
  answers `404` whatever the decision, so missing and foreign tasks
  can't be told apart. Tasks from before owners were stamped have the
  owner `__legacy__`, which is nobody's.
- `ListTasks` asks for `all` and `own` (in parallel): `all` allowed
  lists every task, else `own` allowed lists the caller's tasks, else
  `403`. The answer is applied in the database query, with the user's
  filters and page token, and evaluated again for every page.
- `CreateTask` sends a fixed projection of the submitted task: `name`,
  `tags`, `resources` (without `backend_parameters`), `volumes`,
  `executors[].image`, and `inputs`/`outputs` with `url`, `path`,
  `type`. Commands, environments and input contents are never sent.
  URLs with a `scheme://` prefix lose any `user:password@`, query and
  fragment; they are left out if the part before the first `/` has an
  `@` after a `?` or `#`, or a backslash, or if the host is empty and
  the path has an `@` (the host would be ambiguous). Other values are
  sent unchanged, fragment included, unless they contain `@` or `?`,
  in which case they are left out. Any value with a tab or line break
  is left out.
- Tags and other task fields are what the client submitted, not facts.
- Each request carries a new `X-Request-ID`, which Poiesis logs with
  the decision.

Poiesis refuses to start if `claims` or `credentialFile` is set
without `url`, or if `url` isn't `http(s)`.

### Failures

A timeout (`timeout` seconds for the whole call), a connection error, a
status other than `200`, a body that isn't JSON or a `decision` that is
missing or not a boolean all deny with `503 service_unavailable` and
`Retry-After: 1`; the cause is logged, and nothing is executed.

### Transport and credential

The connection must be secured (AuthZEN 1.0, section 11.1): a loopback
sidecar, mesh mTLS or HTTPS. Poiesis logs a warning for plain `http`
to a non-loopback host and leaves transport to the mesh. Add a
NetworkPolicy so that only Poiesis reaches the service.

If the service authenticates Poiesis, put a bearer credential in a
Secret, mount it into the API pod (`extraVolumes`,
`extraVolumeMounts`) and set `credentialFile` to its path. Poiesis reads
it at startup (an empty file refuses to start) and sends
`Authorization: Bearer <credential>`. After rotating the Secret,
restart the API pods.

## Behaviour the client sees

| Situation                                        | Result                       |
| ------------------------------------------------ | ---------------------------- |
| No or invalid token, userinfo failure            | `401`                        |
| Token type or client not accepted by the issuer  | `401`                        |
| Missing required scope                           | `403`                        |
| API key without the operation's scope            | `403`                        |
| Delegated token, no decision service, actor not in `actors` | `403`             |
| The issuer's claim rule fails                    | `403` on every action        |
| Decision service denies create or both list sets | `403`                        |
| Decision service denies get                      | `404`                        |
| Decision service denies cancel                   | `403` if readable, else `404` |
| Task doesn't exist                               | `404`                        |
| Decision service fails or times out              | `503`, `Retry-After: 1`      |

Every get or cancel, even of a random ID, costs a call to the
decision service; a cancel costs two (`CancelTask`, then `GetTask`)
unless it is allowed for an existing task, so a missing task never
costs fewer calls than an existing one. Rate-limit at the gateway.
Poiesis reads the task from its database before asking, which for a
missing task takes slightly less time than for an existing one; the
decision call dominates either way.

Independent of authorization, Poiesis assigns task IDs, state, creation
time and logs itself and ignores client-supplied values (the TES API
marks them read-only), so a client can't probe for a task by creating
one with its ID.
