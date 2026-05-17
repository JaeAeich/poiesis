DROP INDEX IF EXISTS tasks_principal_idx;
ALTER TABLE tasks DROP COLUMN IF EXISTS principal;
