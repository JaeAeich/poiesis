[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Python 3.13.0](https://img.shields.io/badge/python-3.13.0-blue.svg)](https://www.python.org/)
[![Website](https://vercelbadge.vercel.app/api/jaeaeich/poiesis)](https://poiesis.vercel.app)

# poiesis

<div align="center">
  <img src="./docs/app/public/logo/logo.png" alt="Poiesis Logo" width="300" />
  <br>
  <em>TES (Task Execution Service) on kubernetes</em>
</div>

A [GA4GH TES][tes] task execution service for Kubernetes.

> ⚠️ **Notice — v2 redesign in progress.** Poiesis is being reworked into its
> next major version for better stability, simpler operations, and audit-grade
> behaviour. Expect **`main` to be broken or partially-broken at times** during
> this work. If you need a known-good build, check out the latest release tag.

## Development

```sh
mise install        # tools + venv
lefthook install    # git hooks
mise run dev        # start the API
mise run checks     # run all checks with auto-fix
```

Other tasks: `mise tasks`.

## License

[Apache License 2.0](./LICENSE).

[tes]: https://github.com/ga4gh/task-execution-schemas
