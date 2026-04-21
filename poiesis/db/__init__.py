"""Database access layer.

Free async functions over an asyncpg connection. Pool lifecycle lives in
`pool.py`; per-aggregate persistence in sibling modules (e.g. `tasks.py`).

Schema migrations live in `./migrations/` at the repo root and are applied
out-of-band by `golang-migrate/migrate` — typically as a Helm init container
ahead of the API rollout. This package does not run DDL.

The function signatures here are the SQL contract that the planned Rust
rewrite must re-implement. Keep them narrow and stable.
"""

from poiesis.db import tasks
from poiesis.db.pool import create_pool

__all__ = ["create_pool", "tasks"]
