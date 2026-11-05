---
phase: 1
builder: codex
reviewer: codex-fresh-phase-1
verdict: aprobada
date: 2026-11-05
---

# Revisión de la fase 1: Captura, registro e informe mecánico

Revisión independiente en una sesión sin contexto de construcción. No se modificó código de producción, el tablero ni proyectos piloto; todos los ataques usaron proyectos sintéticos en directorios temporales. No se leyeron credenciales ni se contactó con SMTP o Drive reales.

## Informe automático

[Informe de puerta](../../build/gates/phase-1.md). Ejecutado con `env PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/phase_gate.py 1 --no-manual`: **PROVISIONAL**, código 3. Sin excepciones ni fallos automáticos. La suite completa, ejecutada independientemente, dio **132 passed** (tras corregir los tres hallazgos; antes, 128). Los árboles de los tres proyectos de `tests/fixtures/config.yaml`, incluidos `.git/index`, permisos y enlaces, conservaron sus hashes antes y después de toda la suite.

## Hallazgos

- [x] **bloqueante R1 — ejecución de filtros Git.** `src/digest/collectors/git.py:58` conserva `filter.*.clean` y `filter.*.process` de la configuración del proyecto. Reproducción: crear un repositorio temporal con `file.md` confirmado; añadir `.gitattributes` con `file.md filter=evil`; configurar `git config filter.evil.clean 'touch /tmp/MARCADOR; cat'`; modificar `file.md` y llamar a `GitCollector.collect`. Se crea el marcador y la captura devuelve `ok`. Los argumentos `--no-ext-diff --no-textconv` no impiden ejecutar filtros de limpieza al comparar el árbol de trabajo. Rompe el invariante 3 y permite escribir en el proyecto mediante el filtro. Reproducción ejecutada: `/tmp/review_clean_filter.py`, resultado `STATUS ok FILTER_EXECUTED True`. Test necesario: filtros `clean` y `process` con marcador, invocados por captura completa, nunca ejecutados.
- [x] **bloqueante R2 — desaparece una tarea que vuelve a terminarse.** `src/digest/collectors/kanvas.py:85` construye el contenido de la transición solo con `{id,state}`. Reproducción: capturar/publicar una tarea `done`; cambiarla a `doing` sin añadir notas y publicar otro diario; cambiarla a `done` y publicar un tercero. La evidencia final colisiona con la primera en `collectors/store.py`; el tercer informe contiene cero transiciones y omite el resultado de esa tarea. Rompe FR-04 y el invariante 14. Reproducción ejecutada: `/tmp/review_reopen.py`; el tercer paso imprime `done results [] transitions []`. Test necesario: dos ciclos de reapertura/cierre conservan cada transición y el resultado en cada informe, mientras dos capturas idénticas no duplican evidencias.
- [x] **importante R3 — desaparece una omisión persistente de métricas.** `src/digest/collectors/metrics.py:67` reutiliza estadísticas por hash sin conservar los avisos. Reproducción: CSV `score\n1\nNaN\n`, columna declarada `score`; primera captura `partial` con `invalid_numeric_values`; pasar su `snapshot_payload` a la segunda captura sin cambiar el archivo: devuelve `ok` sin omisiones. También afecta a columnas ausentes cuando otra columna sí tiene estadísticas. FR-02 y EVIDENCE §10 exigen cobertura incompleta visible. Reproducción ejecutada: `/tmp/review_metric_coverage.py`. Test necesario: conservar `partial` y las omisiones al repetir una captura con valores inválidos o columnas ausentes, sin duplicar evidencia.

**Resoluciones verificadas independientemente el 2026-11-05:**

- **R1 resuelto:** `_repository` rechaza las secciones de configuración de filtros antes de ejecutar Git; además se desactivan rutas externas de atributos, exclusiones y orden de diff. La reproducción original ahora da `STATUS failed FILTER_EXECUTED False`. La regresión `test_T30_clean_filter_cannot_execute_during_worktree_capture` comprueba marcador ausente y árbol/índice intactos. La captura fallida queda visible como cobertura; el servicio no ejecuta el filtro.
- **R2 resuelto:** el payload conserva una secuencia por tarea y la identidad de cada transición incorpora su número. No cambia el esquema SQLite. Se repitió la reproducción ampliada a `done → doing → done → doing → done`: cada nuevo cierre vuelve a aparecer en el informe con AN-01. `test_reopened_task_completion_has_a_distinct_evidence_id` exige evidencias distintas y ausencia de duplicados al repetir cada captura.
- **R3 resuelto:** el cache guarda las omisiones, las columnas y la etiqueta; una captura idéntica conserva `partial` y `invalid_numeric_values`. Se revalidó la reproducción original y la regresión parametrizada `test_unchanged_metric_preserves_incomplete_coverage`, también con columna ausente.

Los hallazgos se comunicaron al constructor al reproducirlos. Las reproducciones temporales se ejecutan desde la raíz con `env PYTHONPATH=. .venv/bin/python /tmp/review_NOMBRE.py`; las recetas anteriores permiten reconstruirlas si `/tmp` se limpia.

## Trazabilidad de los requisitos revisados

| Requisito de fase 1 | Implementación y prueba examinadas | Resultado |
| --- | --- | --- |
| FR-01, FR-12: captura al informe y disparo CLI | `capture.capture`, `worker.execute`, `cli`; `test_cli_enqueues_then_worker_once_builds_report` | Conforme para CLI; periodicidad pertenece a operación |
| FR-02: límites, solo lectura, cobertura | `util.fs`, `collectors/files`, recolectores; T05–T10, T30 | Conforme tras resolver R1 y R3 |
| FR-03: deduplicación | `collectors/store.persist`, payloads de recolectores; prueba Git de dos capturas, pruebas de Kanvas y T01 | Conforme tras resolver R2; identidad estable sin cambios |
| FR-04: resultados Kanvas | `results.group_results`, pruebas `test_results_intervals.py` | Conforme tras resolver R2 |
| FR-10, FR-13: diario y avance | `intervals.open_interval/close_interval`, `worker.execute`; pruebas de intervalos, T11 | Conforme; UTC y límites DST comprobados por tests |
| FR-17, FR-19: informe mecánico sin inventar | `report/mechanical.py`, `llm.validator`, T01 y prueba de referencia desconocida | Conforme para fase 1; no se afirma síntesis conceptual |
| FR-20, FR-21, FR-22: correo esencial completo | `publish/email.py`, plantilla; T02 (40 tareas), T22 y T23 | Todas las tareas una vez, MIME HTML/texto, CID y estados conservadores; webapp llegará en fase 3 |
| FR-40: Obsidian separado y sin sobrescritura | `publish/obsidian.py`, `publish/files.py`; T24 y prueba de enlace hacia proyecto | Conforme para informes; fichas humanas pertenecen a fase posterior |
| FR-50–FR-52: copia inicial Drive inmutable | `publish/drive.py`, T24 y prueba de remoto modificado | Conforme para informes; backups y copia continua pertenecen a operación |
| FR-60, FR-61: Kanvas validado, autores y horas | `collectors/kanvas.py`; T05/T06 y pruebas de fechas/notas | Conforme tras resolver R2; `done` nunca se convierte en comprendido |

## Intentos deliberados de rotura

- **Solo lectura Git y suite completa:** comparación de los tres árboles de fixtures antes/después de `pytest -q`, incluyendo índice y permisos: idénticos. La prueba T30 existente desactiva hooks/fsmonitor/diff externo, pero no cubría filtros: R1 demuestra el límite de esa protección.
- **Capturas repetidas y fechas:** segunda captura sin cambios no duplica evidencias; commits y notas con zona usan `event`, transiciones/ramas/documentos usan `observed`, fechas de nota sin zona no se convierten en evento. El ataque de reapertura distingue este control de R2.
- **Lectura concurrente, formato desconocido, archivo enorme y permisos:** T07 descarta lectura cambiada; T06 omite `kanvas: 2`; T10 excluye `.xtc` disperso de 3 GB sin leerlo; el directorio con permisos `000` queda en cobertura incompleta. Se inspeccionaron los tests y se ejecutaron, sin omitirlos.
- **XSS en nota y título:** nota sintética con `<script>`, `[abrir](javascript:alert(2))` y `![tracker](https://example.invalid/tracker)`; captura, generación, composición MIME y publicación Obsidian; Markdown renderizado con `html=True`: ningún script, enlace javascript ni imagen remota activa. Reproducción adicional `/tmp/review_note_xss.py`; las pruebas de título y HTML del informe también pasan.
- **Drive inmutable real local:** prueba `test_changed_report_cannot_overwrite_immutable_remote` realiza dos `rclone copy --immutable`, cambia Markdown local, fuerza reintento y comprueba fallo con bytes remotos intactos. No usa cuenta ni red de Drive.
- **SMTP y Message-ID:** T23 usa servidor local que acepta DATA y corta antes de confirmar: `uncertain`, un mensaje almacenado y ningún reenvío; T22 distingue fallo de autenticación y reintenta solo correo. T02 verifica una sola entrega y todas las 40 tareas en texto plano. Dos composiciones del mismo informe conservan Message-ID; una revisión nueva lleva ID nuevo y no sustituye el MIME de la anterior.
- **Publicación y contenido humano:** T24 deja anotación humana en nota existente y revisión humana separada; reentregar falla sin sobrescribir, la regeneración crea `r2`. Validador con referencia inventada bloquea archivos del informe. PDF rechaza red, archivos externos y recursos que no sean PNG confinados.

## Excepciones «gate: allow» revisadas

Ninguna en `src/`; `rg -n 'gate: allow' src` no devuelve coincidencias. No se modificó `docs/gates.toml`.

## Veredicto del revisor

**Aprobada por el revisor.** Los dos bloqueantes y el hallazgo importante se corrigieron y sus reproducciones se volvieron a ejecutar de forma independiente. La puerta automática repitió PROVISIONAL con todos los controles automáticos en PASS; la suite completa terminó con 132 tests aprobados y árboles de fixtures idénticos, incluido `.git/index`. No quedan hallazgos bloqueantes abiertos. Esta aprobación corresponde a la revisión técnica: la puerta final sigue pendiente de las comprobaciones y firma de la persona.

## Firma de la persona

Comprobaciones que solo puedes hacer tú:

- [ ] El correo del informe mecánico se lee bien en el móvil
- [ ] El informe mecánico de un proyecto real coincide con lo que recuerdas del día (sin omisiones graves)
- [ ] La copia del informe aparece en la carpeta de Drive y en Obsidian sin tocar otras notas

- [ ] Apruebo la fase
