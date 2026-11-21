-- Indexes for ListTasks (issue #167).
--
-- Pages are ordered `creation_time DESC, id DESC` with a keyset cursor on
-- `(creation_time, id)`, and callers are scoped to their own tasks
-- (`owner = $me`). Tag filters use `tags ? key` and `tags @> {key: value}`,
-- which a GIN index on the jsonb column serves.
--
-- Plain CREATE INDEX, not CONCURRENTLY: golang-migrate runs each file as
-- one multi-statement exec, which Postgres wraps in a transaction, and
-- CONCURRENTLY can't run inside one. Writes to `tasks` wait while the
-- indexes build.

CREATE INDEX IF NOT EXISTS tasks_owner_creation_idx
  ON tasks (owner, creation_time, id);

-- Replaces `tasks_creation_idx`, which this one covers.
CREATE INDEX IF NOT EXISTS tasks_creation_id_idx ON tasks (creation_time, id);
DROP INDEX IF EXISTS tasks_creation_idx;

CREATE INDEX IF NOT EXISTS tasks_tags_idx ON tasks USING gin (tags);
