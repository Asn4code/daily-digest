PRAGMA foreign_keys = ON;

CREATE TABLE project (
  id TEXT PRIMARY KEY,                 -- estable, de la configuración
  name TEXT NOT NULL,
  root TEXT NOT NULL,
  objective TEXT,
  priority INTEGER NOT NULL DEFAULT 1,
  external_allowed INTEGER NOT NULL DEFAULT 1,
  config_hash TEXT NOT NULL
);

CREATE TABLE snapshot (
  id INTEGER PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES project(id),
  source TEXT NOT NULL,                -- kanvas | git | docs | figures | metrics | runs | ...
  taken_at TEXT NOT NULL,              -- UTC ISO
  schema_version TEXT,
  content_hash TEXT,
  payload_path TEXT,                   -- copia acotada en data_dir/snapshots/
  status TEXT NOT NULL CHECK (status IN ('ok','partial','failed')),
  error TEXT
);

CREATE TABLE evidence (
  id TEXT PRIMARY KEY,                 -- ev_<sha256[:12]> de (project, source, locator, content_hash)
  project_id TEXT NOT NULL REFERENCES project(id),
  source TEXT NOT NULL,
  kind TEXT NOT NULL,                  -- task_transition | task_note | commit | diff | doc_change | figure | metric | run | ...
  locator TEXT NOT NULL,               -- ruta#línea, sha de commit, ID de tarea, job de Slurm...
  observed_at TEXT NOT NULL,
  event_at TEXT,
  time_quality TEXT NOT NULL CHECK (time_quality IN ('event','observed')),
  content_hash TEXT NOT NULL,
  excerpt TEXT NOT NULL,               -- acotado a limits.max_excerpt_chars
  meta TEXT NOT NULL DEFAULT '{}',     -- JSON
  task_id TEXT,                        -- ID de Kanvas si aplica
  snapshot_id INTEGER REFERENCES snapshot(id),
  UNIQUE (project_id, source, locator, content_hash)
);

CREATE TABLE result (
  id TEXT PRIMARY KEY,                 -- res_<proyecto>_<tarea o hash>
  project_id TEXT NOT NULL REFERENCES project(id),
  task_id TEXT,
  title TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  completed_at TEXT,
  review_state TEXT NOT NULL DEFAULT 'pending'
    CHECK (review_state IN ('pending','submitted','contrasted','needs_clarification','closed_by_human','postponed'))
);

CREATE TABLE result_evidence (
  result_id TEXT NOT NULL REFERENCES result(id),
  evidence_id TEXT NOT NULL REFERENCES evidence(id),
  PRIMARY KEY (result_id, evidence_id)
);

CREATE TABLE interval (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('daily','weekly','preview')),
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  closed INTEGER NOT NULL DEFAULT 0,
  requested_by TEXT NOT NULL CHECK (requested_by IN ('timer','web','cli'))
);

CREATE TABLE report (
  id TEXT PRIMARY KEY,                 -- rep_<kind>_<fecha o semana>_r<n>
  interval_id INTEGER NOT NULL REFERENCES interval(id),
  revision INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('generating','ready','mechanical','failed')),
  model_info TEXT NOT NULL DEFAULT '{}',      -- JSON: proveedor y modelo por sección
  prompt_versions TEXT NOT NULL DEFAULT '{}', -- JSON
  coverage TEXT NOT NULL DEFAULT '{}',        -- JSON: fuentes ok/parciales/fallidas, omitidos
  json_path TEXT, md_path TEXT, html_path TEXT, pdf_path TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (interval_id, revision)
);

CREATE TABLE report_evidence (
  report_id TEXT NOT NULL REFERENCES report(id),
  evidence_id TEXT NOT NULL REFERENCES evidence(id),
  PRIMARY KEY (report_id, evidence_id)
);

CREATE TABLE plan_item (
  id INTEGER PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES report(id),
  kind TEXT NOT NULL CHECK (kind IN ('mission','warmup')),
  action TEXT NOT NULL,
  done_criterion TEXT NOT NULL,
  dependency TEXT,
  reason TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('kanvas','model','review')),
  kanvas_task_id TEXT,
  accepted INTEGER NOT NULL DEFAULT 0,
  edited_text TEXT                      -- versión ajustada por la persona
);

CREATE TABLE review (
  id TEXT PRIMARY KEY,                 -- rev_<result_id>_<n>
  result_id TEXT NOT NULL REFERENCES result(id),
  proposed_in_report TEXT REFERENCES report(id),
  mode TEXT CHECK (mode IN ('full','short','minimal')),
  human_text TEXT,                     -- JSON con los campos del modo
  submitted_at TEXT,
  contrast TEXT,                       -- JSON (schemas.Contrast)
  decision TEXT CHECK (decision IN ('closed','needs_clarification','postponed')),
  decided_at TEXT,
  doubts TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE delivery (
  id INTEGER PRIMARY KEY,
  report_id TEXT REFERENCES report(id),
  review_id TEXT REFERENCES review(id),
  channel TEXT NOT NULL CHECK (channel IN ('email','obsidian','drive')),
  state TEXT NOT NULL CHECK (state IN ('pending','sent','failed','uncertain')),
  attempts INTEGER NOT NULL DEFAULT 0,
  message_id TEXT,
  remote_ref TEXT,
  last_error TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE (report_id, review_id, channel)
);

CREATE TABLE job (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('daily','weekly','preview','capture','deliver','backup','contrast')),
  params TEXT NOT NULL DEFAULT '{}',
  requested_by TEXT NOT NULL CHECK (requested_by IN ('timer','web','cli')),
  state TEXT NOT NULL CHECK (state IN ('queued','running','done','failed','skipped')),
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  error TEXT
);

CREATE TABLE llm_call (
  id INTEGER PRIMARY KEY,
  job_id INTEGER REFERENCES job(id),
  task TEXT NOT NULL,                  -- extract | conceptual | plan | weekly | contrast
  provider TEXT NOT NULL, model TEXT NOT NULL,
  prompt_name TEXT NOT NULL, prompt_version TEXT NOT NULL,
  input_tokens INTEGER, output_tokens INTEGER, latency_ms INTEGER,
  ok INTEGER NOT NULL, error TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- schema_version, last_closed_daily, ...
