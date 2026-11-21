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

Tasks are **visible to their owner only** by default, with or without a
decision service. Only with [sharing](#sharing) turned on
(`authz.sharing`) may a decision service show a task to anyone else.

When both the rule and the decision service are set, **both must
allow**. Everything else (entitlements, roles, admin rights, image or
resource limits, GA4GH Passport visas) belongs in the decision service,
not in Poiesis. Both need `auth.enabled: true`; Poiesis refuses to
start otherwise.

![Authorization: before and after](/authz.gif)

## Configuration

The decision service's Helm values map 1:1 to
`POIESIS_AUTHZ_DECISION_SERVICE_*` environment variables (lists are
JSON arrays, since values such as group URNs may contain commas), and
`sharing` and `maxOwners` to `POIESIS_AUTHZ_SHARING` and
`POIESIS_AUTHZ_MAX_OWNERS`. Claim rules are set per issuer, in
`auth.issuers[]` (`POIESIS_AUTH_ISSUERS`).

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
  sharing: false      # POIESIS_AUTHZ_SHARING; see "Sharing" below
  maxOwners: 1000     # POIESIS_AUTHZ_MAX_OWNERS
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
retries) in the `tes-authzen/2` profile, and allows only on `200` with
`{"decision": true}` and no obligations. The profile is TES-wide: its
keys live under `context.tes`, so one decision service can serve
Poiesis, TESK, Funnel and other TES implementations alike.

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
    "properties": {
      "owner": "...", "state": "RUNNING", "tags": {}, "groups": []
    }
  },
  "context": {"tes": {"profile": "tes-authzen/2", "service_id": "org.ga4gh.poiesis"}}
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
  key, `iss`, `sub`, `client_id` and `claims` come from the snapshot
  of the minting token (see
  [Deprovisioning lag](./api-keys.md#deprovisioning-lag)), so a policy
  written for tokens applies to keys unchanged; `scope` is the key's
  own (`tasks:read`, `tasks:write`). Use `via` to treat keys
  differently.
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
  | `GetTask`    | `tes_task` with `owner`, `state`, `tags`, `groups` | `404`   |
  | `CancelTask` | `tes_task` with `owner`, `state`, `tags`, `groups` | `403` if `GetTask` is allowed, else `404` |
  | `ListTasks`  | `tes_task_set` `own` (and `all` with sharing on) | `403` if all asked sets are denied |

  `GetTask` and `ListTasks` carry `action.properties.view`.
- `groups` are the groups the task is shared with: set only by a
  `CreateTask` decision with sharing on (see [Sharing](#sharing)),
  otherwise empty. They are never taken from the creator's claims.
- With sharing on, Poiesis asks about a missing task too, with empty
  properties, and answers `404` whatever the decision, so missing and
  foreign tasks can't be told apart. With sharing off, it asks only
  about the caller's own tasks (see [Sharing](#sharing)). Tasks from
  before owners were stamped have the owner `__legacy__`, which is
  nobody's.
- `ListTasks` is answered in the database query, with the user's
  filters and page token, and asked again for every page.
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

Poiesis refuses to start if `claims`, `credentialFile` or `sharing` is
set without `url`, or if `url` isn't `http(s)`.

### Response

A plain AuthZEN answer is enough:

```json
{"decision": true}
```

The decision may be refined under `context.tes`; every field is
optional:

```json
{
  "decision": true,
  "context": {
    "tes": {
      "scope": {
        "owners": ["<owner id>"],
        "groups": ["lab-alpha"],
        "tags": {"project": ["x", "y"]}
      },
      "groups": ["lab-alpha"],
      "obligations": [],
      "advice": ["..."],
      "reason": "member of lab-alpha"
    }
  }
}
```

| Field         | Type                     | Used for                    | Meaning |
| ------------- | ------------------------ | --------------------------- | ------- |
| `scope`       | object (below)           | `ListTasks` on `own`        | Other owners' tasks the caller may list too |
| `groups`      | list of strings          | `CreateTask`                | Groups to share the new task with |
| `obligations` | list of strings          | every action                | What Poiesis must do to allow; any one denies |
| `advice`      | list of strings          | none                        | Accepted and ignored |
| `reason`      | string                   | the log                     | Logged with the decision, never sent to the client |

`scope` and `groups` take effect only with sharing on (see
[Sharing](#sharing)) and are ignored on any other action.

- **`scope`** has up to three dimensions: `owners` (owner ids),
  `groups` (matched against the task's `groups`) and `tags` (an object
  of tag keys to lists of values). A task matches if it matches every
  dimension present, and it matches a dimension if any one of its
  values does: its owner is one of `owners`, its `groups` share one
  with `groups`, or its tags hold one of the key/value pairs. So
  `{"groups": ["lab-alpha"], "tags": {"project": ["x", "y"]}}` is "in
  lab-alpha, and tagged project x or y". The caller lists their own
  tasks and the ones the scope matches. An absent or empty scope adds
  none, and so does a dimension with no values. The scope is a fixed
  vocabulary turned into parameterised SQL, never a raw predicate.
- **`maxOwners`**: a scope naming more than `authz.maxOwners` (default
  1000) distinct owners is denied with `403` and logged as an error
  naming the limit, so a runaway policy can't build an unbounded query.
  Use `groups` or `tags` for large audiences.
- **`obligations`**: Poiesis knows no obligation yet, so any obligation
  turns an allow into a deny (as any deny: `403` for create and list,
  `404` for get), logged as a warning with the obligation names. An
  empty list is no obligation.
- **`advice`**: accepted, ignored.
- **`reason`**: logged with the decision and its `X-Request-ID`; the
  client gets the usual `403` or `404` only.

Unknown keys of `context` and `context.tes` are ignored, so the profile
can grow. Unknown scope dimensions are not: every dimension must
match, so ignoring one would widen the scope, and the answer fails
like a broken service (see [Failures](#failures)). So does a present
field of the wrong type; `null` is not the same as absent. The
[response cases](https://github.com/jaeaeich/poiesis/blob/dev/tests/unit/golden/authz/responses.json)
in the test suite list valid and malformed answers with their meaning,
next to the golden requests.

### Sharing

Tasks reference and contain data (inputs, outputs, logs, environment)
that is usually granted to one person, so **a task is visible to its
owner only by default**, whatever the decision service answers.
Showing tasks to anyone else, admins and group members included, is an
operator opt-in:

```yaml
authz:
  sharing: false  # POIESIS_AUTHZ_SHARING (true/false); needs decisionService.url
  maxOwners: 1000 # POIESIS_AUTHZ_MAX_OWNERS
```

An unrecognised `POIESIS_AUTHZ_SHARING` value (anything but
`true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`) refuses to start. A
decision service decides who may run tasks either way; sharing decides
whether it can also show a task to someone else.

| Operation    | Sharing off (default)                                   | Sharing on |
| ------------ | ------------------------------------------------------- | ---------- |
| `CreateTask` | Asked; `groups` in the decision ignored                 | Asked; the decision's `groups` stored with the task |
| `ListTasks`  | One question on `own`: allowed lists the caller's tasks, denied is `403`; `scope` ignored | `all` and `own` asked in parallel: `all` allowed lists every task, else `own` allowed lists the caller's tasks and its `scope`'s, else `403` |
| `GetTask`    | Own task: asked. Foreign or missing task: `404`, not asked | Asked for every task, foreign and missing ones included |
| `CancelTask` | Own task: asked. Foreign or missing task: `404`, not asked | Asked for every task, foreign and missing ones included |

Without a decision service, the built-in owner rule applies either way.
With sharing off, a foreign and a missing task get the same `404`,
both without a call to the decision service. With sharing on, admin
read access is just policy: the decision service allows `all` (or a
foreign `GetTask`) for whoever it considers an admin.

### No decision cache

Poiesis doesn't cache decisions. A safe cache key would have to cover
everything the decision service sees (claims, task state, tags,
groups, `view`), or a cached allow would answer a different question.
If you need a cache, put it in the decision service or its sidecar,
which knows what its policy depends on.

### Migrating from `tes-authzen/1`

`tes-authzen/1` is replaced, without a compatibility mode:

- `context.tes.profile` is `tes-authzen/2`; accept it (or stop checking
  it) in your decision service.
- `tes_task` resources carry `groups` (empty unless sharing put some
  there).
- With sharing off (the default), `ListTasks` asks `own` only, and
  get or cancel of a foreign or missing task isn't asked at all: a
  policy that allowed `all` for admins needs `authz.sharing: true` to
  keep doing so.
- `context.tes` in the response is new. A service that only ever
  answered `{"decision": …}` works unchanged; one that sent other keys
  there must make sure they have the types above.

### Failures

A timeout (`timeout` seconds for the whole call), a connection error, a
status other than `200`, a body that isn't JSON, a `decision` that is
missing or not a boolean, or a malformed `context.tes` all deny with
`503 service_unavailable` and `Retry-After: 1`; the cause is logged, and
nothing is executed.

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
| Decision service denies create or every asked list set | `403`                  |
| Decision service sends an obligation             | Deny (`403`, `404` for get)  |
| List scope names more than `maxOwners` owners    | `403`                        |
| Decision service denies get                      | `404`                        |
| Decision service denies cancel                   | `403` if readable, else `404` |
| Foreign task, sharing off                        | `404`, decision service not asked |
| Task doesn't exist                               | `404`                        |
| Decision service fails, times out or answers malformed | `503`, `Retry-After: 1` |

With sharing on, every get or cancel, even of a random ID, costs a call
to the decision service; a cancel costs two (`CancelTask`, then
`GetTask`) unless it is allowed for an existing task, so a missing task
never costs fewer calls than an existing one. Rate-limit at the
gateway. Poiesis reads the task from its database before asking, which
for a missing task takes slightly less time than for an existing one;
the decision call dominates either way. With sharing off, only the
caller's own tasks cost a call; foreign and missing ones cost none.

Independent of authorization, Poiesis assigns task IDs, state, creation
time and logs itself and ignores client-supplied values (the TES API
marks them read-only), so a client can't probe for a task by creating
one with its ID.
