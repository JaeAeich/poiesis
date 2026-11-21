# Authorization

Poiesis decides who may do what to which task in three layers, each
optional except the first:

1. **Authentication** ([Authentication](./authentication.md)): a valid
   token of a configured issuer (audience, `requiredScopes`), optionally
   enriched with userinfo. Poiesis stamps the caller's owner id
   (`issuer|subject`) on every task it creates.
2. **Claim rule** (`authz.requiredClaim`): an admission gate, "who may
   use this service at all", checked on every TES call.
3. **Decision** (`authz.decisionService`): "what may this caller do".
   Without a decision service, the built-in owner rule applies: anyone
   admitted may create tasks and sees and cancels only their own, and
   delegated tokens (with an `act` claim) are refused.

When both the rule and the decision service are set, **both must
allow**. Everything else (entitlements, roles, admin rights, image or
resource limits, GA4GH Passport visas) belongs in the decision service,
not in Poiesis. Both need `auth.enabled: true`; Poiesis refuses to
start otherwise.

![Authorization: before and after](/authz.gif)

## Configuration

Helm values map 1:1 to `POIESIS_AUTHZ_*` environment variables (lists
are JSON arrays, since values such as group URNs may contain commas).

```yaml
authz:
  requiredClaim:
    name: ""          # POIESIS_AUTHZ_REQUIRED_CLAIM_NAME; empty = off
    values: []        # POIESIS_AUTHZ_REQUIRED_CLAIM_VALUES
    prefixes: []      # POIESIS_AUTHZ_REQUIRED_CLAIM_PREFIXES
  decisionService:
    url: ""           # POIESIS_AUTHZ_DECISION_SERVICE_URL; empty = owner rule
    timeout: 2        # POIESIS_AUTHZ_DECISION_SERVICE_TIMEOUT (seconds)
    claims: []        # POIESIS_AUTHZ_DECISION_SERVICE_CLAIMS
    credentialFile: "" # POIESIS_AUTHZ_DECISION_SERVICE_CREDENTIAL_FILE
```

## Claim rule

The rule looks up the claim `name`: the exact name first (so URI-named
claims such as `https://example.org/groups` work), then as a dotted
path (`realm_access.roles`); in the access token first, then in
userinfo if [userinfo](./authentication.md#user-info) is on. The caller
is admitted if the claim is a string or a list of strings with a value
that equals one of `values` or starts with one of `prefixes`. A missing
claim or another type is a `403`, before any decision service call.
Poiesis refuses to start with a name but no values or prefixes, values
or prefixes but no name, or an empty value or prefix.

Prefixes are compared as raw strings, so include the delimiter. For
LS Login groups, admit a group and its subgroups with the group as an
exact value and its subgroup prefix ending in `:`:

```yaml
authz:
  requiredClaim:
    name: eduperson_entitlement
    values:
      - "urn:geant:lifescience-ri.eu:group:example-vo#login.aai.lifescience-ri.eu"
    prefixes:
      - "urn:geant:lifescience-ri.eu:group:example-vo:"
```

Without the trailing `:`, the prefix would also admit
`…:group:example-vo2#…`.

Every caller needs the claim, including service clients
(client-credentials tokens) and callers behind a gateway such as
proTES, which Poiesis sees as the caller. Their tokens usually carry no
user entitlements, so they get `403`. For such deployments, leave the
rule unset and express "entitled users or client X" in the decision
service (e.g. by `subject.properties.client_id`).

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
    "id": "<owner id: issuer|subject, as stamped on tasks>",
    "properties": {
      "iss": "...", "sub": "...", "client_id": "...", "scope": ["..."],
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
  ids**, today `<issuer>|<subject>` (the subject being the issuer's
  `principalClaim`, `sub` by default). Compare them with each other,
  but don't parse them: their format may change. Use
  `subject.properties.iss` and `sub` for identity-based rules.
- `subject.properties.actor` is present only for a delegated token: the
  RFC 8693 `act` claim's `sub` and `iss` (default: the token's issuer).
  The subject is still the owner; your policy decides what the actor
  may do on the subject's behalf (see
  [Delegation](./authentication.md#delegation)).
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
| Missing required scope                           | `403`                        |
| Delegated token, no decision service             | `403`                        |
| Claim rule fails                                 | `403` on every action        |
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
