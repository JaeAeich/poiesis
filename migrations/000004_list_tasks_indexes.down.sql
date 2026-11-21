-- Reverse of 000004_list_tasks_indexes.up.sql.

DROP INDEX IF EXISTS tasks_tags_idx;
CREATE INDEX IF NOT EXISTS tasks_creation_idx ON tasks (creation_time);
DROP INDEX IF EXISTS tasks_creation_id_idx;
DROP INDEX IF EXISTS tasks_owner_creation_idx;
