---
description: One JSON line per authorization outcome and API key event on the API's stdout - fields, events, request ids and retention.
---

# Audit log

Poiesis writes one line of JSON to the API's standard output for every
authorization outcome of a TES call and for every API key event: who
asked, for what, and what was decided. It answers "who did what" for
incident response and offboarding; keeping, shipping and alerting on
the lines is the job of your log pipeline (Fluent Bit, Vector, Loki,
…), not of Poiesis.

## Configuration

The audit log is **on by default**:

```yaml
audit:
  enabled: true  # POIESIS_AUDIT_ENABLED (true/false)
```

An unrecognised `POIESIS_AUDIT_ENABLED` value (anything but
`true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`) refuses to start, so a
typo can't turn the trail off.

The lines come from the logger `poiesis.audit`, which has a handler of
its own: they don't depend on `logLevel` or on the format of the
application log, and they are not repeated there. Every audit line is a
complete JSON object on one line, without colours or prefixes; other
lines on stdout (the application log, the web server's) are not JSON
objects with an `event` and an `outcome`, so a pipeline can tell them
apart, e.g. by parsing each line as JSON and keeping those with an
`event`.

## Format

```json
{"ts":"2026-11-21T09:00:00.123Z","event":"task.cancel","outcome":"allow","request_id":"3f2c…","owner":"https://keycloak.example.org/realms/poiesis|7d1e…","issuer":"https://keycloak.example.org/realms/poiesis","via":"oidc","credential_id":"b3c4…","client":"poiesis-cli","decided_by":"builtin","admin":true,"task_id":"6d7e…"}
```

Every line has:

| Field | Meaning |
| --- | --- |
| `ts` | Time of the decision, RFC 3339, UTC, milliseconds. |
| `event` | What was asked, see [Events](#events). |
| `outcome` | `allow`, `deny`, or `error` when the decision service (or, for an owner's keys, the database) failed (the client got `503`). |
| `request_id` | The request's id, also sent back in the `X-Request-ID` response header (see [Request id](#request-id)). |

and, about the caller, when known:

| Field | Meaning |
| --- | --- |
| `owner` | The caller's owner id (`namespace\|subject`), as stamped on their tasks. |
| `issuer` | The issuer of the caller's token (for a key, the configured issuer with the key's namespace). |
| `via` | How the caller authenticated: `oidc` (access token), `apikey` or `anonymous` (auth disabled). |
| `credential_id` | The token's `jti`, or the API key's id. |
| `client` | The token's OAuth client (`azp`, else `client_id`). |
| `actor` | `{"iss": …, "sub": …}` of a delegated token (RFC 8693 `act`). |

Fields without a value are left out, not `null`.

**Never in a line**: tokens, API keys, key hashes, claim values (groups,
entitlements, …) or task contents. A line names identifiers only, so it
can be kept longer and shown to more people than the data itself.

## Events

### Tasks

`task.create`, `task.get`, `task.list` and `task.cancel`, one per TES
call, with:

| Field | Meaning |
| --- | --- |
| `decided_by` | `builtin` (claim rule, owner rule, built-in admin, key scopes, `maxOwners`) or `decision_service`. |
| `admin` | `true` when only the built-in [admin](../concepts/authorization.md#admin) rule allowed it (with `adminRead`), else `false`. |
| `task_id` | The task (absent for lists, and for a create that was refused). |
| `list_scope` | For allowed lists: `own`, `all` or `own+scope` (own tasks and those of the decision service's scope). |

A `deny` covers every refusal: the claim rule, a key without the
operation's scope, a delegated token without a decision service, a deny
of the decision service, and a get or cancel of a foreign or missing
task (`404`). The outcome is that of authorization: a create that is
allowed and then fails in Kubernetes is still an `allow`.

### API keys

| Event | When | Fields |
| --- | --- | --- |
| `apikey.mint` | A key is minted, or minting is refused | `key_id`, `scopes`, `expires_at` (allowed only) |
| `apikey.revoke` | A caller revokes one of their keys; `deny` for a key that isn't theirs or doesn't exist | `key_id` |
| `apikey.revoke_owner` | All keys of an owner are revoked ([offboarding](../concepts/api-keys.md#offboarding)) | `target_owner`, `count` (allowed only), `admin` |
| `apikey.list_owner` | An owner's keys are listed by an admin | `target_owner`, `count` (allowed only), `admin` |

They carry `decided_by` too. Refusals (a key or a delegated token
trying to manage keys, a client that may not mint, a caller who isn't
an admin) are `deny`; the reason of a refused mint is in the
application log, at `WARNING`. Listing one's own keys isn't audited.

## Request id

The request id ties an audit line to the client's view and to the
application log:

- A client (or a gateway in front) may send `X-Request-ID`: a value of
  1 to 128 printable ASCII characters without spaces is kept, anything
  else replaced by a new UUID.
- Without one, Poiesis makes a UUID.
- Either way, the response carries it back in `X-Request-ID`, the audit
  lines of the request have it as `request_id`, and the application
  log's decision lines name it as `API request …`. The decision service
  gets an id of its own per call, logged on the same line.

A client-sent id is not checked for uniqueness: use it for correlation,
not as evidence.

## Example lines

A built-in admin (with `adminRead`) lists every task and cancels one of
someone else's:

```json
{"ts":"2026-11-21T09:00:00.123Z","event":"task.list","outcome":"allow","request_id":"a1…","owner":"https://kc.example.org/realms/poiesis|admin-id","issuer":"https://kc.example.org/realms/poiesis","via":"oidc","client":"poiesis-cli","decided_by":"builtin","admin":true,"list_scope":"all"}
{"ts":"2026-11-21T09:00:05.456Z","event":"task.cancel","outcome":"allow","request_id":"b2…","owner":"https://kc.example.org/realms/poiesis|admin-id","issuer":"https://kc.example.org/realms/poiesis","via":"oidc","client":"poiesis-cli","decided_by":"builtin","admin":true,"task_id":"6d7eb20d-…"}
```

A workflow engine's key polls a task the decision service doesn't show
it, and the service is briefly down on the next call:

```json
{"ts":"2026-11-21T09:01:00.000Z","event":"task.get","outcome":"deny","request_id":"c3…","owner":"https://kc.example.org/realms/poiesis|bob-id","issuer":"https://kc.example.org/realms/poiesis","via":"apikey","credential_id":"9a8b…","client":"poiesis-cli","decided_by":"decision_service","admin":false,"task_id":"0c1d…"}
{"ts":"2026-11-21T09:01:30.000Z","event":"task.get","outcome":"error","request_id":"d4…","owner":"https://kc.example.org/realms/poiesis|bob-id","issuer":"https://kc.example.org/realms/poiesis","via":"apikey","credential_id":"9a8b…","client":"poiesis-cli","decided_by":"decision_service","admin":false,"task_id":"0c1d…"}
```

An admin offboards a user; elsewhere, an API key tries to mint a key
of its own (keys can't):

```json
{"ts":"2026-11-21T10:00:00.000Z","event":"apikey.revoke_owner","outcome":"allow","request_id":"e5…","owner":"https://kc.example.org/realms/poiesis|admin-id","issuer":"https://kc.example.org/realms/poiesis","via":"oidc","client":"poiesis-cli","decided_by":"builtin","admin":true,"target_owner":"https://kc.example.org/realms/poiesis|bob-id","count":2}
{"ts":"2026-11-21T10:05:00.000Z","event":"apikey.mint","outcome":"deny","request_id":"f6…","owner":"https://kc.example.org/realms/poiesis|carol-id","issuer":"https://kc.example.org/realms/poiesis","via":"apikey","credential_id":"5e6f…","client":"poiesis-cli","decided_by":"builtin"}
```

Once revoked, a key fails authentication (`401`) and writes no audit
line: see below.

## Retention

Poiesis keeps nothing: the lines go to stdout, and the container
runtime keeps them only until the Pod's log rotates or the Pod goes
away. Ship them to a store with the retention your policies require,
with access limited to the people who may see who did what. Owner ids
and client ids are personal data in many settings; treat the store like
any other log of user activity.

Failed authentication (`401`: no, invalid or expired credentials) has
no principal and is not in the audit log; it is logged at `WARNING` in
the application log, and rate-limiting belongs at the gateway.
