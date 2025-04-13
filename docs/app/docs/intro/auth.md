# Authentication

Poiesis has an abstracted auth design, making it very easy to swap out the
underlying auth provider. Supporting bearer token based authentication.

## Bearer token

The bearer token is a JSON Web Token (JWT) that is used to authenticate requests
to the API.

### OIDC via Keycloak

`Keycloak` is an open-source Identity and Access Management solution that
provides Single Sign-On (SSO) capabilities through OpenID Connect (OIDC). If you
use [Keycloak](https://www.keycloak.org/) as your auth provider, `Poiesis`
integrates seamlessly with it.

### Dummy Auth

If you prefer to keep things simple and not have any auth, you can use the
dummy auth provider. This will make `Poiesis` accepts any token
in its request and validate it.

::: warning Not recommended
This is only recommended for testing and development, do **NOT** use in production.
:::
