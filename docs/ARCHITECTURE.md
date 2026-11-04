# Arquitectura

Un recolector determinista llena un registro SQLite. Del registro salen los informes (diario, semanal, avance) y la webapp. Un único proceso *worker* ejecuta todo el trabajo pesado desde una cola; temporizadores, botones y CLI solo encolan.

```text
 fuentes (proyectos, kanvas.json, sacct, logs)
        │  solo lectura
        ▼
 collectors ──► SQLite (evidence, result, interval…) ◄── web (lee, guarda revisiones, encola jobs)
                       │
                       ▼
                 report builder ── llm.router (Qwen3.6 / NaN) ── llm.validator
                       │
                       ▼
                 publish: email · obsidian · drive (+ deliveries)
```

## 1. Estructura del repositorio

```text
daily-digest/
  AGENTS.md  CLAUDE.md  README.md  kanvas.json  Makefile  pyproject.toml
  config.example.yaml
  deploy/systemd/            # unidades (ver OPERATIONS.md)
  docs/
  src/digest/
    cli.py                   # typer: doctor, capture, run, worker, web, deliver, backup, restore
    config.py                # modelos pydantic + carga YAML
    db/
      __init__.py            # conexión (WAL, foreign_keys=ON), migraciones
      migrations/0001_init.sql
    collectors/
      base.py                # protocolo Collector, EvidenceDraft
      kanvas.py  git.py  docs.py  figures.py  metrics.py  runs.py
      notebooks.py  structures.py  agent_sessions.py   # fase 2
    results.py               # agrupación de evidencias en resultados
    intervals.py             # apertura y cierre de intervalos
    llm/
      client.py              # cliente OpenAI-compatible (httpx)
      router.py              # proveedor por tarea, respaldo, registro llm_call
      schemas.py             # modelos pydantic de las salidas
      validator.py           # IDs, cifras, límites
      prompts/*.md           # con front matter: name, version
    report/
      model.py               # representación común del informe
      mechanical.py          # informe sin LLM
      builder.py             # orquesta extracción, síntesis, plan
      render_md.py  render_html.py  pdf.py
      templates/             # Jinja2: email.html, email.txt, report.html, report.md
    review/
      select.py              # resultado propuesto del día
      contrast.py            # contraste explicación ↔ evidencias
    publish/
      email.py  obsidian.py  drive.py  deliveries.py
    web/
      app.py                 # FastAPI
      routes/  templates/  static/   # htmx copiado localmente, manifest.webmanifest, icons
    extensions/              # fase 6, ver EXTENSIONS.md
      registry.py            # descubre extensiones internas y por entry points
      pack.py                # construye y valida el paquete de contexto
      protocol/  teaching/  methods/  group_meeting/
    mcp/server.py            # fase 6: servidor MCP de solo lectura
    worker.py                # bucle de cola con bloqueo
    util/
      fs.py                  # safe_path, lectura acotada, detección de cambios durante lectura
      proc.py                # run(): lista de args, timeout, entorno mínimo
      hashing.py  timeutil.py  ids.py
  tests/
    fixtures/                # proyectos sintéticos (ver TESTING.md)
    unit/  integration/  e2e/
```

## 2. CLI

| Comando | Qué hace |
| --- | --- |
| `digest doctor` | Valida configuración, rutas, `kanvas check`, proveedores (petición sintética), SMTP, rclone y Tailscale. No modifica nada. |
| `digest capture [--project ID]` | Captura y guarda evidencias. |
| `digest run [--weekly \| --preview] [--now] [--no-send] [--since ISO --until ISO]` | Encola un informe; con `--now` lo ejecuta en primer plano. |
| `digest enqueue KIND --requested-by timer` | Solo inserta un trabajo en la cola (lo usan los temporizadores; `KIND` = daily, weekly, capture, backup). |
| `digest worker` | Procesa la cola (un trabajo cada vez). |
| `digest web` | Arranca la webapp en `web.bind:web.port`. |
| `digest deliver --retry [--channel email\|obsidian\|drive]` | Reintenta entregas pendientes o fallidas (nunca las inciertas sin `--force-uncertain`). |
| `digest backup` / `digest restore --from DIR` | Copia consistente de SQLite / restauración. |
| `digest brief TIPO RESULT_ID [--zip]` | Fase 6: crea un brief de una extensión a partir de un resultado cerrado. |
| `digest extensions` | Fase 6: lista las extensiones registradas y sus capacidades. |
| `digest mcp` | Fase 6: servidor MCP de solo lectura por stdio. |

## 3. Esquema SQLite (`0001_init.sql`)

```sql
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
```

### Migración de la fase 6 (`0002_extensions.sql`)

```sql
CREATE TABLE opportunity (
  id TEXT PRIMARY KEY,                 -- opp_<extensión>_<hash>
  extension TEXT NOT NULL,             -- protocol | teaching | methods | group_meeting | externa
  extension_version TEXT NOT NULL,
  project_id TEXT NOT NULL REFERENCES project(id),
  result_ids TEXT NOT NULL,            -- JSON
  reason TEXT NOT NULL,
  proposed_in_report TEXT REFERENCES report(id),
  state TEXT NOT NULL CHECK (state IN ('proposed','accepted','dismissed','briefed')),
  brief_used TEXT,                     -- URL o ruta del contenido generado fuera, si la persona la anota
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE brief (
  id TEXT PRIMARY KEY,                 -- AAAA-MM-DD-<extensión>-<result_id>
  opportunity_id TEXT REFERENCES opportunity(id),
  extension TEXT NOT NULL,
  pack_version INTEGER NOT NULL,
  path TEXT NOT NULL,                  -- data_dir/briefs/<id>/
  created_at TEXT NOT NULL
);

CREATE TABLE brief_result (
  brief_id TEXT NOT NULL REFERENCES brief(id),
  result_id TEXT NOT NULL REFERENCES result(id),
  PRIMARY KEY (brief_id, result_id)
);
```

## 4. Semántica de intervalos

- **Diario:** `start = end` del último diario cerrado (o inicio del día si no hay); `end = ahora`. Se cierra al publicar.
- **Diario automático tras uno manual:** si existe un diario cerrado hoy y no hay evidencias nuevas desde su `end`, el job queda `skipped`.
- **Avance:** mismo cálculo que el diario, `closed = 0`, sin entregas.
- **Semanal:** sábado 00:00 anterior a sábado 00:00 actual, en `Europe/Madrid`. Manual: los 7 días completos anteriores a hoy.
- **Recuperación:** al arrancar el worker, si faltan diarios de días con evidencias, encola uno por día pendiente (máximo 7).

## 5. Configuración (`config.example.yaml`)

```yaml
timezone: Europe/Madrid

schedule:
  daily: "20:00"
  weekly: "Sat 10:00"
  capture_every_hours: 2
  max_generation_minutes: 60

paths:
  data_dir: /var/lib/daily-digest
  obsidian_vault: /home/USER/Obsidian/Vault
  obsidian_digest_dir: Digest
  obsidian_reviews_dir: Revisiones
  obsidian_briefs_dir: Briefs        # fase 6

projects:
  - id: proj-a
    name: "Proyecto A"
    root: /home/USER/proyectos/proj-a
    objective: "Objetivo científico en una frase"
    priority: 1
    external_allowed: true
    kanvas: kanvas.json
    include: ["**/*.md", "**/*.rst", "docs/**", "results/**", "figures/**", "notebooks/**/*.ipynb", "logs/**"]
    exclude: ["**/*.xtc", "**/*.dcd", "**/*.nc", "**/*.mrc", "data/raw/**", ".venv/**", "**/.env", "**/*.key"]
    figures: ["figures/**/*.png", "results/**/*.png", "results/**/*.svg", "results/**/*.pdf"]
    metrics:
      - label: "Docking"
        pattern: "results/**/scores.csv"
        columns: [rmsd, score]
    runs:
      slurm: { enabled: true, user: USER }
      logs: ["logs/**/*.log", ".snakemake/log/*.log", ".nextflow.log"]
    agent_sessions: []          # fase 2, ver EVIDENCE.md

limits:
  max_file_bytes: 2000000
  max_excerpt_chars: 4000
  max_diff_chars_per_file: 6000
  max_project_package_chars: 200000
  capture_timeout_seconds: 300

llm:
  providers:
    internal: { base_url: "https://QWEN_HOST/v1", model: "qwen3.6", api_key_env: QWEN_API_KEY, timeout_s: 180 }
    nan:      { base_url: "VER_NAN_DOCS", model: "POR_DEFINIR", api_key_env: NAN_API_KEY, timeout_s: 300 }
  routing:                       # orden = preferencia; el segundo es el respaldo
    extract:    [internal, nan]
    conceptual: [nan, internal]
    plan:       [nan, internal]
    weekly:     [nan, internal]
    contrast:   [nan, internal]

email:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  username: USER@gmail.com
  password_env: SMTP_PASSWORD
  from: USER@gmail.com
  to: USER@gmail.com

drive:
  remote: "gdrive:DailyDigest"
  backups_keep_days: 30

web:
  bind: 127.0.0.1
  port: 8090
  public_base_url: "https://HOST.TAILNET.ts.net"
  allowed_tailscale_login: USER@gmail.com    # si la cabecera de Tailscale está presente, debe coincidir

kanvas:
  cli: kanvas                    # o ruta a kanvas.py
  write_enabled: false
```

Los valores `VER_NAN_DOCS` y `POR_DEFINIR` se fijan en la fase 0 (ver `DECISIONS.md`).

## 6. Representación común del informe

`report/model.py` define dataclasses (o modelos pydantic) que alimentan todos los renders: `Report`, `Highlight`, `ProjectBalance`, `ResultEntry`, `PlanItem`, `OpenThread`, `TechnicalNote`, `Coverage`, `Figure`. Cada elemento con texto lleva `evidence: list[str]`. Markdown, HTML, correo y PDF se generan desde esta estructura; nunca desde la salida bruta del modelo.

## 7. Rutas de datos

```text
/opt/daily-digest/            código y venv
/etc/daily-digest/            config.yaml, secrets.env (0600)
/var/lib/daily-digest/
  digest.db
  snapshots/<proyecto>/<fecha>/...
  reports/<kind>/<id>/report.json, report.md, report.html, report.pdf, figures/
  outbox/                     correos generados (para reconciliar estados inciertos)
  briefs/<id>/                fase 6: manifest.json, context.json, context.md, instructions.md, figures/
  backups/digest-AAAA-MM-DD.db
```
