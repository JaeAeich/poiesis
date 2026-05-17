-- Adds the opaque subject identifier the API stamps on every task it
-- creates. Held as `text` rather than `uuid` because OIDC `sub` claims
-- are case-sensitive strings up to 255 chars — not UUIDs — and the
-- column will also carry service-account / group / tenant identifiers
-- when the Authorizer plugin lands. See poiesis/api/auth.py.
--
-- Existing rows backfill to the `__legacy__` sentinel so the owner-only
-- filter naturally hides them from every real principal. Operators who
-- want to assign them to a real owner run an UPDATE post-migration.

ALTER TABLE tasks
  ADD COLUMN principal text NOT NULL DEFAULT '__legacy__';

ALTER TABLE tasks
  ALTER COLUMN principal DROP DEFAULT;

CREATE INDEX tasks_principal_idx ON tasks (principal);

COMMENT ON COLUMN tasks.principal IS
  'Opaque subject identifier from OIDC (sub claim by default). May be a user, '
  'service account, group, or tenant — semantics defined by the operator''s '
  'Authorizer plugin. The literal value ''__anonymous__'' is reserved for '
  'requests served with auth.enabled=false; ''__legacy__'' for rows that '
  'pre-date this column.';
