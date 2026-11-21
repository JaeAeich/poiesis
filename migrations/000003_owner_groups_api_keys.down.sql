DROP TABLE IF EXISTS api_keys;

DROP INDEX IF EXISTS tasks_groups_idx;
ALTER TABLE tasks DROP COLUMN IF EXISTS groups;

ALTER INDEX tasks_owner_idx RENAME TO tasks_principal_idx;
ALTER TABLE tasks RENAME COLUMN owner TO principal;

COMMENT ON COLUMN tasks.principal IS
  'Opaque subject identifier from OIDC (sub claim by default). May be a user, '
  'service account, group, or tenant — semantics defined by the operator''s '
  'Authorizer plugin. The literal value ''__anonymous__'' is reserved for '
  'requests served with auth.enabled=false; ''__legacy__'' for rows that '
  'pre-date this column.';
