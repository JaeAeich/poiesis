-- Reverse of 000001_initial_schema.up.sql.

DROP TABLE IF EXISTS executor_logs;
DROP TABLE IF EXISTS task_logs;
DROP TABLE IF EXISTS task_executors;
DROP TABLE IF EXISTS task_outputs;
DROP TABLE IF EXISTS task_inputs;
DROP TABLE IF EXISTS tasks;

DROP TYPE IF EXISTS tes_file_type;
DROP TYPE IF EXISTS tes_state;
