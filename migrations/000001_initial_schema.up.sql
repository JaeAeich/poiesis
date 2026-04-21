-- 0001: initial schema for the Poiesis Task store.
--
-- Mirrors the GA4GH TES task shape (TesTask + nested arrays) as a fully
-- relational tree. JSONB is reserved for opaque user metadata only
-- (`tasks.tags`, `tasks.backend_parameters`).
--
-- See docs/adr/0004 for the modelling decisions.

CREATE TYPE tes_state AS ENUM (
  'UNKNOWN',
  'QUEUED',
  'INITIALIZING',
  'RUNNING',
  'PAUSED',
  'COMPLETE',
  'EXECUTOR_ERROR',
  'SYSTEM_ERROR',
  'CANCELED',
  'PREEMPTED',
  'CANCELING'
);

CREATE TYPE tes_file_type AS ENUM ('FILE', 'DIRECTORY');

CREATE TABLE tasks (
  id                          UUID PRIMARY KEY,
  state                       tes_state    NOT NULL DEFAULT 'UNKNOWN',
  name                        TEXT,
  description                 TEXT,
  -- Resources (task-level; per-executor overrides deferred per ADR-0001).
  cpu_cores                   INTEGER,
  preemptible                 BOOLEAN,
  ram_gb                      DOUBLE PRECISION,
  disk_gb                     DOUBLE PRECISION,
  zones                       TEXT[],
  backend_parameters          JSONB,
  backend_parameters_strict   BOOLEAN NOT NULL DEFAULT FALSE,
  -- Volumes are an array of mount paths shared across executors.
  volumes                     TEXT[],
  -- Opaque user metadata.
  tags                        JSONB,
  creation_time               TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Lifecycle bookkeeping (written by TRec / TCtl as per ADR-0003).
  ended_at                    TIMESTAMPTZ,
  termination_reason          TEXT,
  -- K8s linkage (populated by the API when the Job is submitted).
  pod_name                    TEXT
);

CREATE INDEX tasks_state_idx        ON tasks (state);
CREATE INDEX tasks_creation_idx     ON tasks (creation_time);
CREATE INDEX tasks_name_prefix_idx  ON tasks (name text_pattern_ops);

CREATE TABLE task_inputs (
  id                INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id           UUID         NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  ordinal           INTEGER      NOT NULL,
  name              TEXT,
  description       TEXT,
  url               TEXT,
  path              TEXT         NOT NULL,
  type              tes_file_type NOT NULL DEFAULT 'FILE',
  content           TEXT,
  streamable        BOOLEAN,
  UNIQUE (task_id, ordinal)
);
CREATE INDEX task_inputs_task_idx ON task_inputs (task_id);

CREATE TABLE task_outputs (
  id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id       UUID         NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  ordinal       INTEGER      NOT NULL,
  name          TEXT,
  description   TEXT,
  url           TEXT         NOT NULL,
  path          TEXT         NOT NULL,
  path_prefix   TEXT,
  type          tes_file_type NOT NULL DEFAULT 'FILE',
  UNIQUE (task_id, ordinal)
);
CREATE INDEX task_outputs_task_idx ON task_outputs (task_id);

CREATE TABLE task_executors (
  id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id        UUID    NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  ordinal        INTEGER NOT NULL,
  image          TEXT    NOT NULL,
  command        TEXT[]  NOT NULL,
  workdir        TEXT,
  stdin          TEXT,
  stdout         TEXT,
  stderr         TEXT,
  env            JSONB,
  ignore_error   BOOLEAN,
  UNIQUE (task_id, ordinal)
);
CREATE INDEX task_executors_task_idx ON task_executors (task_id);

CREATE TABLE task_logs (
  id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id     UUID        NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  ordinal     INTEGER     NOT NULL,
  metadata    JSONB,
  start_time  TIMESTAMPTZ,
  end_time    TIMESTAMPTZ,
  system_logs TEXT[],
  outputs     JSONB,
  UNIQUE (task_id, ordinal)
);
CREATE INDEX task_logs_task_idx ON task_logs (task_id);

CREATE TABLE executor_logs (
  id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_log_id  INTEGER     NOT NULL REFERENCES task_logs(id) ON DELETE CASCADE,
  ordinal      INTEGER     NOT NULL,
  start_time   TIMESTAMPTZ,
  end_time     TIMESTAMPTZ,
  stdout       TEXT,
  stderr       TEXT,
  exit_code    INTEGER     NOT NULL,
  UNIQUE (task_log_id, ordinal)
);
CREATE INDEX executor_logs_task_log_idx ON executor_logs (task_log_id);
