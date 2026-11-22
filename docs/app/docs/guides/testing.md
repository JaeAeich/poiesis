---
description: Run Poiesis's unit tests, its end-to-end tests on a kind cluster and the GA4GH TES compliance suite locally, as CI does.
---

# Testing

CI runs three kinds of tests on every pull request. Each can be run from
a checkout. Install the tools first with `mise install` and
`uv sync --all-extras --all-groups`.

## Unit tests

```sh
uv run pytest
```

The SQL tests (`tests/unit/*_db.py`) need a Postgres. Without
`POIESIS_TEST_DATABASE_URL` they are skipped. Each test applies the
migrations in a schema of its own and drops it afterwards, so any
database you can create schemas in works:

```sh
docker run -d --rm --name poiesis-test-pg -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres postgres:16-alpine
POIESIS_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres \
  uv run pytest
```

CI also sets `POIESIS_TEST_REQUIRE_DATABASE=1`, which turns the skip
into an error.

## Chart

```sh
mise run chart:lint
```

This checks `values.schema.json`, then runs `helm lint --strict` and
`helm template` with every values file in `deployment/helm/poiesis/ci/`.

## End-to-end tests

The tests in `tests/e2e/` run tasks through the TES API of a real
deployment and check their final state, logs and staged files. They need
`docker`, `kind`, `kubectl` and `helm`.

`tests/e2e/setup.sh` creates a kind cluster named `poiesis-e2e`, builds
the images from the checkout, deploys Postgres and one emulator per
object store (SeaweedFS for S3, fake-gcs-server for GCS, Azurite for
Azure; `tests/e2e/deps.yaml`) and installs the chart with auth off and
all three stores on (`tests/e2e/values.yaml`):

```sh
tests/e2e/setup.sh
kubectl --context kind-poiesis-e2e -n poiesis port-forward svc/poiesis-api 8000:8000 &
POIESIS_E2E_URL=http://localhost:8000 uv run pytest tests/e2e
```

- The tests reach fake-gcs-server and Azurite through their own
  `kubectl port-forward` (local ports 14443 and 20000), unless
  `POIESIS_E2E_GCS_URL` and `POIESIS_E2E_AZURE_URL` name them.
- The GCS emulator is `tustvold/fake-gcs-server`, a fork of
  fake-gcs-server with the XML API obstore uses. It has no uploads in
  parts, so the GCS case keeps its files small.
- Run `setup.sh` again after a change: it rebuilds the images and
  upgrades the release. `SKIP_BUILD=1` reuses the images.
- The test of an image that doesn't exist waits for the 5-minute pending
  timeout, so it is left out by default. Run it with `-m slow`.
- A test that fails because of a known bug is marked
  `xfail(strict=True)` with its issue number. Once the bug is fixed the
  test passes, which fails the run: remove the mark then.

Delete the cluster when done:

```sh
kind delete cluster --name poiesis-e2e
```

## TES compliance suite

`tests/e2e/compliance.sh` runs the [GA4GH TES compliance
suite](https://github.com/ga4gh/openapi-test-runner) for TES 1.1.0
against the same deployment and fails unless every test passes:

```sh
tests/e2e/compliance.sh http://localhost:8000
```

It fetches a pinned commit of the suite and installs it with `uv` in a
temporary directory. The suite creates tasks, so run it against a test
deployment, not a production one.
