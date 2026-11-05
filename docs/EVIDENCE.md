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

## 6. Utilidades de lectura (fase 0)

`safe_path(root, relative, exclude=(), max_bytes=2000000)` devuelve una ruta de
archivo regular validada. Rechaza rutas absolutas y componentes `..`, enlaces fuera
de la raíz, exclusiones obligatorias y configuradas, y archivos demasiado grandes.
Las exclusiones se aplican al nombre solicitado y al destino del enlace.

Los recolectores deben leer con `read_bounded` (mismos argumentos), que abre en solo
lectura mediante descriptores sin seguir enlaces tras validar, acota los bytes y
compara identidad, tamaño, mtime y ctime antes y después. Devuelve bytes o `ReadError`
con un motivo estable (`excluded`, `outside_root`, `too_large`, `not_regular`,
`unreadable`, `changed_during_read`). Las exclusiones obligatorias no se desactivan
con `exclude: []`.

`digest.util.proc.run(args, timeout=..., cwd=...)` exige una lista de argumentos y
un timeout positivo y finito. Devuelve código de salida, stdout y stderr; un timeout
o fallo de arranque produce `ProcessError` sin argumentos ni salida capturada.
No hereda el entorno del usuario ni sus credenciales: usa el PATH del sistema,
locale UTF-8 y Git sin bloqueos opcionales, prompts ni configuración global. Para
herramientas instaladas fuera del PATH del sistema, configura una ruta absoluta.

## 7. Capturas de Kanvas (fase 1)

El recolector valida con `kanvas check` una copia temporal de los bytes leídos con
`read_bounded`, fuera del proyecto. Así el proceso de validación no vuelve a abrir
una ruta del proyecto susceptible de sustitución por enlace. La copia se elimina
al terminar; los payloads persistidos se guardan como capturas nuevas en data_dir.

Se comparan estados y notas con la última captura utilizable. Las notas llevan
hora de evento solo si su fecha incluye zona horaria válida; las transiciones de
estado llevan hora observada porque el formato del tablero no enlaza de forma
inequívoca cada transición a una nota. No se utiliza la hora de creación de la
tarea como fecha de finalización. Se conserva el autor de cada nota y se detectan
preguntas por el prefijo `Question:` del CLI.

La persistencia usa el esquema publicado y la clave de deduplicación de evidencia;
repetir una captura no duplica hechos. Los fallos quedan como cobertura y no
sustituyen el último payload utilizable para comparar la siguiente lectura.

## 8. Capturas Git (fase 1)

Git se ejecuta con rutas literales, paginación desactivada, entorno mínimo,
`GIT_OPTIONAL_LOCKS=0`, hooks y fsmonitor desactivados, y diffs sin programas
externos ni textconv. Los binarios se identifican sin incluir su contenido en el
extracto. Los archivos nuevos pasan por la lectura acotada y las exclusiones;
los diffs se truncan por archivo y la cobertura registra ese recorte.

Se rechazan repositorios cuyo directorio Git escape de la raíz, tenga includes
de configuración o almacenes alternativos de objetos. Los worktrees con metadatos
externos quedan como cobertura fallida, no se abren fuera de las raíces permitidas.
El historial se limita a 5000 commits por captura y se avisa si se supera; ramas
nuevas y cambios sin confirmar se registran con hora observada, commits con fecha
de committer. El árbol de prueba, incluido el índice Git, se compara antes y después.

## 9. Documentos y figuras (fase 1)

La exploración no sigue directorios simbólicos, poda exclusiones y se interrumpe
por timeout o tras 100000 entradas, dejando cobertura incompleta visible. Los
Markdown, texto, HTML e informes PDF incluidos generan evidencia `doc_change` con
diff acotado; HTML se extrae como texto sin scripts, estilos ni recursos externos.
PDF se lee sin ejecutar contenido, con límites de páginas y texto. El payload
textual por captura queda acotado por `max_project_package_chars`.

Las figuras PNG/SVG/PDF generan únicamente miniaturas PNG de hasta 1200 px por
lado. SVG bloquea recursos externos; PDF usa solo la primera página. Se limita
la carga de imágenes a 16 millones de píxeles. La procedencia de Git solo se
atribuye si la identidad del blob coincide con los bytes leídos; en otro caso se
marca `unverified`. No se infiere procedencia de la fecha de modificación.

## 10. Métricas declaradas (fase 1)

Los lectores aceptan CSV, TSV y JSON (objeto de una fila o lista de objetos).
Solo resumen columnas declaradas; los ausentes, booleanos, no numéricos y valores
no finitos quedan fuera del cálculo con cobertura incompleta visible. Se guardan
n, media, mediana, mínimo y máximo, además del cambio de cada estadístico frente
a la captura anterior cuando existe. La aritmética evita publicar infinitos; si
un cambio no cabe en un float finito se omite con aviso. No se atribuyen unidades
ni significado científico que no estén declarados en la fuente.

## 11. Evidencias de ejecuciones (fase 1)

Los logs declarados se leen con límites y se comparan por hash. Se guardan hasta
80 líneas finales y el extracto configurado, con cobertura explícita si se recorta.
Solo una fecha ISO con zona horaria explícita se usa como evento; el resto queda
como observado. Un error o fallo de contabilidad Slurm no impide recoger los logs.

`sacct` se consulta únicamente si está habilitado. Los jobs deben tener WorkDir
absoluto dentro del proyecto. Si sus fechas no incluyen zona horaria, no se
inventa una; estado, tiempos y exit code originales siguen disponibles en el
extracto. SGE se cubre inicialmente mediante logs locales existentes; no se
lanzan jobs ni se hacen consultas SSH implícitas.

## 12. Agrupación e intervalos implementados

Los resultados de tareas aceptadas para revisión o terminadas conservan su ID y
su estado humano al reagrupar. Commits con ID explícito de tarea, sus diffs,
figuras con procedencia Git verificada y archivos nombrados explícitamente en
notas pueden asociarse a esa tarea. Lo que no tiene tarea se agrupa por directorio
o fuente como «Fuera del tablero». Las tareas aún abiertas quedan disponibles
como hilos, sin presentarlas como resultados terminados.

Los intervalos se almacenan en UTC y usan medianoches de Europe/Madrid para días
y semanas, incluido el cambio de horario. Un avance no cierra intervalos; un
informe solo permite cerrar su intervalo cuando está listo o es mecánico. La
recuperación propone hasta siete días completos con evidencia no cubierta por
un diario cerrado. Los estados de revisión humana no se actualizan al publicar.
