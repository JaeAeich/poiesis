-- Owners become `issuer|subject` (several issuers may issue the same
-- `sub`), tasks get a `groups` column for group-scoped authorization, and
-- the `api_keys` table is created. See poiesis/api/auth.py.
--
-- Existing owners are NOT rewritten: SQL can't know which issuer they
-- came from. Rows with a bare `sub` simply match nobody until an operator
-- prefixes them with the issuer they belong to:
--
--   UPDATE tasks SET owner = '<issuer>|' || owner
--   WHERE owner NOT IN ('__anonymous__', '__legacy__')
--     AND position('|' in owner) = 0;

ALTER TABLE tasks RENAME COLUMN principal TO owner;

ALTER INDEX tasks_principal_idx RENAME TO tasks_owner_idx;

COMMENT ON COLUMN tasks.owner IS
  'Opaque owner id `issuer|subject`: the configured issuer and the value of '
  'its principal claim (sub by default). The literal value ''__anonymous__'' '
  'is reserved for requests served with auth.enabled=false; ''__legacy__'' '
  'for rows that pre-date owners. Neither ever matches a real caller.';

ALTER TABLE tasks
  ADD COLUMN groups text[] NOT NULL DEFAULT '{}';

CREATE INDEX tasks_groups_idx ON tasks USING gin (groups);

COMMENT ON COLUMN tasks.groups IS
  'Groups the task is shared with, for group-scoped authorization decisions. '
  'Empty when the task is visible to its owner only.';

CREATE TABLE api_keys (
  id               uuid PRIMARY KEY,
  name             text        NOT NULL,
  key_hash         bytea       NOT NULL UNIQUE,
  owner            text        NOT NULL,
  scopes           text[]      NOT NULL DEFAULT '{}',
  claims_snapshot  jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  last_used_at     timestamptz,
  revoked_at       timestamptz
);

CREATE INDEX api_keys_owner_idx ON api_keys (owner);

COMMENT ON TABLE api_keys IS
  'Long-lived API keys, minted by an authenticated owner for clients such as '
  'workflow engines that outlive an access token. Only a hash is stored.';
COMMENT ON COLUMN api_keys.id IS
  'Key id; shown to the owner and logged for audit, never secret.';
COMMENT ON COLUMN api_keys.name IS
  'Owner-chosen label, e.g. the workflow run it was minted for.';
COMMENT ON COLUMN api_keys.key_hash IS
  'SHA-256 of the secret key; the key itself is shown once and never stored.';
COMMENT ON COLUMN api_keys.owner IS
  'Owner id (`issuer|subject`, as tasks.owner) the key authenticates as.';
COMMENT ON COLUMN api_keys.scopes IS
  'Scopes granted to requests made with the key.';
COMMENT ON COLUMN api_keys.claims_snapshot IS
  'Claims of the minting token kept for authorization decisions; they go '
  'stale until the key expires.';
COMMENT ON COLUMN api_keys.created_at IS 'When the key was minted.';
COMMENT ON COLUMN api_keys.expires_at IS
  'When the key stops working; every key expires.';
COMMENT ON COLUMN api_keys.last_used_at IS
  'When the key last authenticated a request; NULL if never.';
COMMENT ON COLUMN api_keys.revoked_at IS
  'When the key was revoked; NULL while it is active.';
