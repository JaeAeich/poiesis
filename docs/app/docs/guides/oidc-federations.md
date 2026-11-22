---
description: Connect Poiesis to an OIDC federation such as LS Login - exact issuer, client id as audience, token type, userinfo for entitlements, entitlement URNs, and API keys.
---

# OIDC federations

Research federations such as
[LS Login](https://lifescience-ri.eu/ls-login/) (Life Science AAI)
work like any OIDC issuer, but differ from a Keycloak realm you run
yourself: you don't control the audience, and group memberships come
from userinfo, not the access token. This page collects what an
issuer entry for LS Login needs; the same checks apply to other
federations.

## The issuer entry

```yaml
auth:
  issuers:
    - issuer: https://login.aai.lifescience-ri.eu/oidc/  # trailing / matters
      audience: my-poiesis-client      # your client id; see below
      clients: [my-poiesis-client]     # optional: only your client's tokens
      tokenTypes: [at+jwt]             # the default; check, see below
      userinfo:
        enabled: true                  # entitlements come from userinfo
      requiredClaim:                   # optional: admit one group
        name: eduperson_entitlement
        values:
          - "urn:geant:lifescience-ri.eu:group:example-vo#aai.lifescience-ri.eu"
        prefixes:
          - "urn:geant:lifescience-ri.eu:group:example-vo:"
```

| Setting | Why |
| --- | --- |
| `issuer` | Matched exactly against the token's `iss`, trailing `/` included. Copy it from the discovery document's `issuer` (`https://login.aai.lifescience-ri.eu/oidc/.well-known/openid-configuration`), not from a browser bar. See [How a token finds its issuer](../concepts/authentication.md#how-a-token-finds-its-issuer). |
| `audience` | LS Login puts the requesting client's id into `aud` and doesn't document resource indicators, so the audience is the client id of whoever obtained the token: yours, or a portal's. A shared client id has a replay risk; see [Shared audience](../concepts/authentication.md#shared-audience). |
| `clients` | Accept only tokens obtained by the clients you list (`azp`, else `client_id`). See [Clients](../concepts/authentication.md#clients). |
| `tokenTypes` | Poiesis accepts `at+jwt` by default (RFC 9068). If your tokens have another header `typ`, list it; see [Token type](../concepts/authentication.md#token-type). |
| `userinfo` | LS Login releases `eduperson_entitlement` at userinfo, not in access tokens. Without userinfo, a claim rule on it refuses everyone with `403`. See [User info](../concepts/authentication.md#user-info). |
| `requiredClaim` | Entitlement URNs end in `#aai.lifescience-ri.eu`. Admit a group with its exact URN and its subgroups with a prefix ending in `:`. See [Claim rule](../concepts/authorization.md#claim-rule). |

## Check your tokens

Federations change, and not everything is documented. Before going
live, decode an access token from your client and check `iss`, `aud`,
`azp` and the header's `typ` (needs jq 1.7 or later, which decodes
unpadded base64):

```sh
# header, then payload
for part in 1 2; do
  jq -R --argjson i "$((part - 1))" 'split(".")[$i] | gsub("-";"+") | gsub("_";"/") | @base64d | fromjson' <<<"$TOKEN"
done
```

and ask userinfo what Poiesis will see:

```sh
curl -s -H "Authorization: Bearer $TOKEN" \
  https://login.aai.lifescience-ri.eu/oidc/userinfo | jq .eduperson_entitlement
```

## Gateways and portals

A portal or gateway in front of Poiesis either forwards the user's
token, sends its own client-credentials token, or exchanges the user's
token (RFC 8693; LS Login's discovery document lists the token-exchange
grant). Each needs different configuration; see
[Claim rule](../concepts/authorization.md#claim-rule) for the three
modes.

## API keys

If you turn on [API keys](../concepts/api-keys.md), a key freezes the
userinfo answer at minting time: a user removed from a group keeps
that group's access through their keys until they expire (90 days by
default). Use a short `maxTtl` or bound `snapshot_age` in the decision
service; see
[Deprovisioning lag](../concepts/api-keys.md#deprovisioning-lag).
`keyMinting.maxAuthAge` needs `auth_time` in access tokens; check with
the decode command above before turning it on.
