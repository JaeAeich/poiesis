---
description: Set up a Keycloak realm for Poiesis - audience and groups mappers, token type, clients for people and CI, key minting, the Swagger UI login and the dev realm.
---

# Keycloak

Poiesis works with any OIDC issuer. This guide covers Keycloak, which
the dev stack ships with; most of it carries over to other IdPs.

<FlowDiagram :spec="{
  title: 'A Keycloak login, end to end',
  h: 200,
  nodes: {
    u: { x: 4, y: 20, w: 104, label: 'Person', sub: 'poiesis-cli' },
    kc: { x: 158, y: 20, w: 104, label: 'Keycloak', sub: 'realm poiesis' },
    api: { x: 312, y: 20, w: 104, label: 'Poiesis', sub: 'aud poiesis' },
    ci: { x: 158, y: 136, w: 104, label: 'CI job', sub: 'poiesis-ci' }
  },
  edges: [['u','kc'],['kc','api'],['ci','kc']],
  hops: [
    { f: 'u', t: 'kc', label: 'login', cap: 'A person logs in with the public client: authorization code with PKCE, or the device flow.' },
    { f: 'kc', t: 'api', label: 'typ JWT', cap: 'The access token carries aud poiesis and a groups claim.' },
    { f: 'ci', t: 'kc', label: 'secret', cap: 'A pipeline uses a confidential client with client credentials.' },
    { f: 'kc', t: 'api', label: 'sub svc', tone: 'ok', cap: 'Its tokens are first-class too; the service account owns its tasks.' }
  ]
}" />

## The realm

1. **Two clients.** A public client for people (`poiesis-cli`: standard
   flow with PKCE `S256`, and the OAuth device grant) and a confidential
   client with service accounts for pipelines (`poiesis-ci`).
2. **An audience mapper** on each client (protocol mapper type
   *Audience*) that adds `poiesis` to access tokens, not ID tokens. Give
   each Poiesis instance an audience of its own; see
   [Audience](../concepts/authentication.md#audience).
3. **A groups mapper** (type *Group Membership*, claim name `groups`) if
   you want claim rules or admins by group. With *Full group path* off,
   values are plain names (`poiesis-admins`); with it on, they are paths
   (`/poiesis-admins`). Match what you write in `requiredClaim` and
   `admin`.

## The issuer entry

```yaml
auth:
  issuers:
    - issuer: https://keycloak.example.org/realms/poiesis
      audience: poiesis
      tokenTypes: [JWT]
      clients: [poiesis-cli, poiesis-ci]
      keyMinting:
        clients: [poiesis-cli]
        maxAuthAge: 600
      requiredClaim: {name: groups, values: [poiesis-users]}
      admin: {name: groups, values: [poiesis-admins]}
```

- **`tokenTypes: [JWT]`**: Keycloak types its access tokens `JWT`, not
  `at+jwt`. It types ID tokens the same, so the check doesn't tell them
  apart: keep `audience` different from every client id (Keycloak's ID
  tokens carry the client id as `aud`). See
  [Token type](../concepts/authentication.md#token-type).
- **`clients`**: tokens of other clients of the realm get `401`.
- **`keyMinting.clients`**: only the client people log in with may mint
  [API keys](../concepts/api-keys.md), never the CI client.
- **`maxAuthAge`**: Keycloak puts `auth_time` in access tokens for
  browser logins (authorization code and device flow) through its
  default `basic` scope, but not for the password grant. Check before
  turning it on.
- **Userinfo**: Keycloak answers userinfo only for tokens requested with
  `scope=openid`. Prefer mapping claims into the access token and leave
  [userinfo](../concepts/authentication.md#user-info) off.
- **Key rotation**: after a Keycloak restart rotates its keys, Poiesis
  refetches them once for an unknown `kid`, at most every 30 s.

## The Swagger UI login

With `auth.swaggerUi` set, people can log in at `<API URL>/docs` and mint
API keys in the browser:

```yaml
auth:
  swaggerUi:
    issuer: https://keycloak.example.org/realms/poiesis
    clientId: poiesis-cli
    scopes: openid
```

The public client needs the redirect URI `<API URL>/docs/oauth2-redirect`
and the API's origin as a web origin (for CORS). The browser talks to
Keycloak directly, so Keycloak must be reachable from it under the issuer
URL. See [From the Swagger UI](../concepts/api-keys.md#from-the-swagger-ui).

## The dev realm

The dev manifest imports a ready-made `poiesis` realm:

| User | Group |
| --- | --- |
| `alice`, `carol` | `lab-alpha` |
| `bob` | `lab-beta` |
| `admin` | `poiesis-admins` |

The password is the user name. User ids are fixed in the realm, so `sub`
(and with it task ownership) survives a Keycloak restart.

| Client | Use |
| --- | --- |
| `poiesis-cli` | Public. Authorization code with PKCE, device flow, and (dev only) the password grant. |
| `poiesis-ci` | Confidential, client credentials. Secret `poiesis-ci-secret`. |

The dev issuer entry accepts both clients (`clients: [poiesis-cli,
poiesis-ci]`), lists `tokenTypes: [JWT]`, lets `poiesis-cli` mint keys,
and makes `poiesis-admins` the built-in admins. Tokens carry
`aud: poiesis` and a `groups` claim, and live five minutes.

Keycloak pins the issuer to the in-cluster URL,
`http://keycloak.deps.svc:8080/realms/poiesis`, so tokens fetched through
the port-forward validate in the API too.

### Browser logins against the dev realm

For browser flows from the host (authorization code, device flow), make
the pinned hostname resolve to the port-forward:

```bash
echo "127.0.0.1 keycloak.deps.svc" | sudo tee -a /etc/hosts
```

Then, with both port-forwards from the [Quickstart](../start/quickstart.md)
running, open <http://localhost:8000/docs>, click **Authorize**, log in
under `oidc` (authorization code) as `alice`, and run
`POST /poiesis/v1/api-keys`. The realm accepts the Swagger UI on
`localhost:8000` and on `localhost:18000`, for a port-forward to
`18000:8000` when 8000 is taken.

### The device flow

`poiesis-cli` requires PKCE for the device flow too:

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
```
