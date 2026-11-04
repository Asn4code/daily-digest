# Evidencias y recolectores

Una evidencia es un hecho verificable con fuente, localizador, hash, hora y un extracto acotado. El informe solo puede afirmar lo que alguna evidencia respalde. Este documento define qué recoge cada recolector y el contrato que todos cumplen.

## 1. Contrato común

```python
class Collector(Protocol):
    source: str                       # "kanvas", "git", ...
    phase: int                        # fase en que se activa
    def collect(self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext) -> CollectorOutput: ...

@dataclass
class EvidenceDraft:
    kind: str
    locator: str                      # único dentro de (proyecto, fuente)
    content: bytes | str              # se hashea; no se guarda entero
    excerpt: str                      # ≤ limits.max_excerpt_chars
    observed_at: datetime
    event_at: datetime | None
    meta: dict[str, Any]
    task_id: str | None = None

@dataclass
class CollectorOutput:
    evidence: list[EvidenceDraft]
    status: Literal["ok", "partial", "failed"]
    omitted: list[Omission]           # ruta + motivo (tamaño, exclusión, error, timeout)
    snapshot_payload: dict | None     # copia acotada para comparar con la próxima captura
```

Reglas para todos los recolectores:

- Leen solo rutas que pasan por `util.fs.safe_path(root, rel)`: ruta resuelta dentro de la raíz, no excluida, tamaño ≤ `limits.max_file_bytes`.
- Si un archivo cambia durante la lectura (mtime o tamaño distinto antes y después), la lectura se descarta y se anota como omisión `changed_during_read`.
- Nunca ejecutan contenido del proyecto. Los únicos procesos permitidos son `git`, `kanvas` (lectura) y `sacct`, vía `util.proc.run`.
- Un fallo en un recolector no detiene a los demás: devuelve `status="failed"` y la cobertura lo muestra.
- Tiempo máximo por proyecto: `limits.capture_timeout_seconds`.

## 2. Fuentes

| Fuente | Fase | Qué se recoge | Cómo | Evidencias (`kind`) |
| --- | --- | --- | --- | --- |
| Kanvas | 1 | Tareas creadas, aprobadas, iniciadas, terminadas; notas (sobre todo las de cierre de los agentes); preguntas `ask` | `kanvas check -b <ruta>`; parseo de `kanvas.json`; diff con la captura anterior | `task_transition`, `task_note`, `task_question` |
| Git | 1 | Commits del intervalo (mensaje, autor, fecha, archivos, líneas), diff por archivo, cambios preparados y sin preparar, archivos nuevos sin seguimiento (filtrados), ramas nuevas | `git log --since --until --numstat`, `git show`, `git diff --cached`, `git diff`, `git status --porcelain=v2` | `commit`, `diff`, `uncommitted` |
| Documentación | 1 | `.md`, `.rst`, `.txt`, README y notas incluidas | Hash; diff unificado contra la versión de la captura anterior | `doc_change` |
| Figuras | 1 | PNG, SVG, PDF nuevos o cambiados en las rutas de `figures` | Hash; miniatura PNG (máx. 1200 px); procedencia: commit que la añadió, script citado en un log o manifiesto | `figure` |
| Métricas | 1 | CSV, TSV o JSON declarados en `metrics` | Lector por patrón; columnas declaradas; estadísticos por código (n, media, mediana, mín., máx.) y cambio frente a la versión anterior | `metric` |
| Ejecuciones | 1 | Jobs de Slurm del usuario; logs de Snakemake, Nextflow o scripts propios | `sacct -u USER -S <since> -E <until> -X -P -o JobID,JobName,State,ExitCode,Elapsed,Start,End,WorkDir`; logs: errores y avisos por patrón, últimas líneas | `run`, `run_error` |
| Notebooks | 2 | Celdas cambiadas, salidas nuevas | `nbformat` sin ejecutar; `execution_count` y metadatos de fecha si existen | `notebook_change` |
| Estructuras | 2 | PDB y mmCIF nuevos | Solo metadatos: nombre, cadenas, número de residuos, cabecera | `structure` |
| Sesiones de agentes | 2 | Transcripciones de Claude Code, Codex u otros | Directorios configurados por proyecto | `agent_session` |

### Detalles por fuente

**Kanvas.** El tablero es `kanvas.json` en la raíz del proyecto (Kanvas 0.4.0, rama `cursor/standalone-html-board-6ccb`, commit `97e93ad`). Formato: `{"kanvas": 1, "title", "groups": [{id, name}], "tasks": [{id, title, state, group, deps, yolo, at, by, desc, notes: [{at, by, text}]}]}`. Estados: `proposed`, `todo`, `doing`, `review`, `done`; «bloqueada» se deriva. Las transiciones se detectan comparando capturas; su hora es la de la nota correspondiente si existe (`event`), si no, la de la captura (`observed`). El autor de cada nota (`claude-code`, `codex`, `human`…) se guarda en `meta.by` y se muestra: no se atribuye al usuario trabajo de un agente o colaborador sin evidencia. Antes de implementar, verificar `kanvas status --json`; si existe y basta, preferirlo al parseo directo.

**Git.** Siempre con `GIT_OPTIONAL_LOCKS=0`, `-c core.quotepath=off` y `--no-pager`. Diff truncado a `limits.max_diff_chars_per_file` por archivo; los binarios se listan sin contenido. Los cambios sin confirmar son «hilos abiertos».

**Figuras.** La figura original no se copia entera al registro; se guarda una miniatura PNG y la ruta. Los SVG se rasterizan (nunca se sirven tal cual). Un notebook con salidas antiguas no cuenta como figura del día salvo que su hash sea nuevo.

**Métricas.** Las cifras que aparezcan en un informe deben salir de aquí o de un extracto literal; el validador lo comprueba (ver `LLM.md`). Ejemplos de columnas típicas: RMSD, pLDDT, pTM, puntuación de docking, energía, métricas de entrenamiento.

**Sesiones de agentes (fase 2).** Probablemente la fuente más rica: explica por qué se hizo cada cambio. Ubicaciones a verificar en la fase 0: Claude Code guarda transcripciones JSONL por proyecto bajo `~/.claude/projects/`; Codex, bajo `~/.codex/sessions/`. Se extrae lo pedido, lo hecho y los archivos tocados; nunca se envían transcripciones completas al modelo sin acotar.

## 3. Exclusiones por defecto

Trayectorias (`.xtc`, `.trr`, `.dcd`, `.nc`), mapas (`.mrc`, `.map`), archivos binarios grandes, entornos (`.venv`, `venv`, `node_modules`, `conda`), `.git` interno, cachés (`__pycache__`, `.snakemake/conda`), secretos (`.env`, `*.key`, `*.pem`, `id_*`). Lo omitido por exclusión no aparece en la cobertura; lo omitido por tamaño, error o timeout sí.

## 4. De evidencias a resultados

`results.py` agrupa evidencias en resultados con estas reglas, en orden:

1. Cada tarea de Kanvas que entra en `review` o `done` en el intervalo es un resultado (`res_<proyecto>_<task_id>`). Se le asignan: sus notas; commits cuyo mensaje cita el ID de la tarea o que ocurren mientras está en `doing` y tocan archivos mencionados en sus notas; figuras, métricas y ejecuciones de esos commits o rutas.
2. Las evidencias sin tarea se agrupan por proyecto y directorio de primer nivel en resultados «fuera del tablero» (`res_<proyecto>_<hash>`).
3. Una evidencia puede pertenecer a más de un resultado; el informe evita repetirla en la sección técnica.

La relevancia de un resultado (para el resultado propuesto a revisar) combina: prioridad del proyecto, si cambia una métrica declarada, si hay figura, si la tarea tiene dependientes, y antigüedad del pendiente. La fórmula concreta se ajusta en el piloto.

## 5. Paquete para el modelo

Para cada resultado se construye un paquete con sus evidencias (ID, tipo, localizador, hora, extracto) dentro de `<evidence id="ev_…">…</evidence>`. El paquete por proyecto no supera `limits.max_project_package_chars`; si se supera, se priorizan notas de cierre, métricas y diffs pequeños, y lo recortado se anota en la cobertura.
