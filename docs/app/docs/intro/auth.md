# Authentication

Poiesis has an abstracted auth design, making it very easy to swap out the
underlying auth provider. Supporting bearer token based authentication.

## Auth Providers

### OIDC (OpenID Connect)

Poiesis supports authentication via any OIDC-compliant provider. This is the
recommended option for production deployments. You can use providers such as
Keycloak, Auth0, Okta, Google, or any other OIDC-compatible service.

#### Configuring OIDC in Poiesis

To enable OIDC authentication, set the following in your `values.yaml`:

```yaml
poiesis:
    auth:
        type: oidc
        oidc:
            issuer: <OIDC_ISSUER_URL>
            clientId: <CLIENT_ID>
            clientSecret: <CLIENT_SECRET>
```

- `issuer`: The OIDC issuer URL (e.g., for Keycloak: `http://keycloak.<namespace>.svc.cluster.local/realms/<realm>`)
- `clientId`: The client ID registered with your OIDC provider
- `clientSecret`: The client secret for your OIDC client

#### Example: Keycloak

[Keycloak](https://www.keycloak.org/) is an open-source Identity and Access
Management solution that provides Single Sign-On (SSO) capabilities through
OIDC. See the [deployment guide](/docs/deploy/deploying-poiesis) for a full
example of using Keycloak with Poiesis.

### Dummy Auth

If you prefer to keep things simple and not have any auth, you can use the
dummy auth provider. This will make Poiesis accept any token in its request and
validate it.

::: warning Not recommended
This is only recommended for testing and development, do **NOT** use in production.
:::
