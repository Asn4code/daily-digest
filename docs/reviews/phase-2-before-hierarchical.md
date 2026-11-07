---
phase: 2
builder: codex
reviewer: codex-fresh-phase-2
verdict: aprobada
date: 2026-11-05
---

# Revisión de la fase 2: Informe multinivel con LLM

Protocolo en docs/VALIDATION.md. El revisor rellena «Hallazgos» y «Veredicto»; la persona rellena «Firma».

## Informe automático

[Informe automático](../../build/gates/phase-2.md): ejecutado con `PATH=$PWD/.venv/bin:$PATH .venv/bin/python scripts/phase_gate.py 2 --no-manual`, resultado PROVISIONAL, código 3. `PATH=$PWD/.venv/bin:$PATH make check` ejecutado por el revisor: lint, formato, tipos y 168 tests pasan tras las correcciones. Sin fallos automáticos; firma humana pendiente.

## Hallazgos

- [x] **bloqueante R2-01, secretos (resuelto):** `src/digest/collectors/notebooks.py:74` conserva una clave sintética conocida en fuente/salida de celdas aunque `ctx.secrets` la declare; `src/digest/report/builder.py:107` incorpora el extracto sin redacción al prompt. La protección existente solo cubre cuerpos de sesiones y no otros recolectores, localizadores ni contexto. Reproducción: notebook con `source='api_key = "SYNTHETIC_SECRET_REVIEW_ONLY"'`, contexto con ese valor en `secrets`; el valor persiste en `output.evidence[0].excerpt`. Regresión necesaria: comprobar claves configuradas y sintaxis de secretos en paquetes, peticiones HTTP simuladas y archivos generados, incluyendo notebooks y contexto; ningún proveedor real.
- [x] **bloqueante R2-02, cifras/unidades (resuelto):** `src/digest/llm/validator.py:54` y `:124` aceptan una afirmación `RMSD 1.4 kg` contra `RMSD 1.4 Å, control 2.0 Å`; además aceptan `RMSD 999nm`, `RMSD 999Å` y `RMSD 2.9Å`. Las unidades desconocidas se degradan a ausencia de unidad, los números pegados a unidades se omiten o se reconocen parcialmente. Reproducción: usar el paquete de `tests/unit/test_llm_validation.py` y reemplazar `facts[0].text` por esas cadenas; `validate` no lanza excepción. Regresión necesaria: rechazar cada variante y aceptar las formas respaldadas con y sin espacio.
- [x] **bloqueante R2-03, interpretación semanal (resuelto):** `src/digest/report/render_md.py:162` imprime `hypotheses_changed` con `claims`, perdiendo `confidence` y la etiqueta de interpretación. HTML sí conserva ambas. Reproducción: hipótesis semanal con texto `El control sugiere sesgo` y `confidence='low'`; el Markdown imprime solo texto y evidencia. Regresión necesaria: comprobar etiqueta/confianza en Markdown/Obsidian y HTML.
- [x] **importante R2-04, antigüedad de pendientes (resuelto):** `src/digest/llm/validator.py:191` compara conjuntos y acepta el orden invertido o duplicados en `review_status.pending`; los renders anuncian orden de mayor a menor antigüedad. Reproducción: dos pendientes con distinta `first_seen_at`, invertir la lista que envía el constructor y validar; la lista pasa. Regresión necesaria: conservar el orden determinista del contexto o validar igualdad ordenada, sin duplicados.

### Revalidación de las correcciones

- R2-01: redacción común en persistencia y antes de construir paquetes/respuestas. La reproducción completa, sin sesiones configuradas, ya no envía ni publica la credencial sintética. `test_secrets_are_removed_from_sources_context_snapshots_and_model_wire` cubre sesiones ausentes/presentes y claves con comillas/backslash, revisando peticiones HTTP simuladas, snapshots y base de evidencias.
- R2-02: el token numérico no retrocede a cifras parciales; las unidades pegadas, desconocidas y compuestas se comparan. Revalidé `999nm`, `999Å`, `2.9Å`, `1.4 kg`, cifras con punto/coma final y pérdida de denominador (`1.4 kJ mol^-1` → `1.4 kJ`, `1.4 kg m^-3` → `1.4 kg`): se rechazan; valores y unidades exactos se aceptan. Regresiones permanentes: `test_free_text_attached_or_unknown_units_cannot_bypass_numeric_checks` y `test_compound_unit_suffix_cannot_be_removed`.
- R2-03 y R2-04: revalidé la etiqueta `Interpretación (confianza low)` en Markdown y el rechazo de una lista de pendientes invertida. Ambas regresiones están incorporadas a `test_T18_weekly_uses_evidence_even_when_daily_report_files_are_missing`.

## Excepciones «gate: allow» revisadas

- No hay excepciones `gate: allow` en `src/`. Las dos excepciones de `scripts/phase_gate.py` permiten procesos para ejecutar las comprobaciones del repositorio; son código de desarrollo fuera del servicio y están justificadas.

## Veredicto del revisor

**Aprobada por la revisión independiente.** Los tres bloqueantes y el problema de orden quedaron corregidos y se revalidaron sus reproducciones; no quedan hallazgos abiertos. Esta aprobación no sustituye la firma humana ni autoriza la fase siguiente sin ella. La revisión se realizó en una sesión fresca, sin participar en la construcción. No se modificó código de producción, tablero ni proyectos piloto y no se llamaron proveedores reales, SMTP ni Drive.

Se contrastaron FR-14–FR-19 con `intervals`, `worker`, `report/mechanical`, `report/builder`, esquemas y renders. El semanal usa evidencias originales; el plazo global limita los intentos LLM; el informe mecánico conserva los resultados y distingue ausencia de evidencia de ausencia de trabajo. La publicación y las entregas repiten la validación. Las propuestas se guardan sin aceptación y la generación no cierra revisiones humanas.

Se revisaron los delimitadores escapados de todos los prompts, el enrutado conservador para paquetes mixtos y planes aceptados, las reparaciones sin cuerpos HTTP, y los límites de paquetes. Los lectores de notebooks no ejecutan código. Codex filtra por cwd de cada turno y excluye herramientas; OpenCode/Hermes usan consultas fijas, raíz resuelta, límites de filas/pasos/texto, conexión inmutable y aviso de WAL, conforme a D-045. No se solicita cambiar el diseño autorizado de SQLite grande.

La orden automática denominada `run-fixtures-llm-fake` produce una salida mecánica al faltar claves: por sí sola no prueba el enriquecimiento. Los tests E2E de `tests/e2e/test_llm_report.py` sí inyectan `httpx.MockTransport` y prueban diario y semanal completos, auditoría, conservación de tareas, propuestas sin aceptación y nueva validación antes de entregas locales. Esta combinación cubre el flujo; los casos adversariales descubiertos requieren sus regresiones específicas. La corrección científica de un informe real y la utilidad del plan siguen pendientes de la firma humana.

Pruebas independientes temporales en `/tmp`, solo con datos sintéticos y HTTP simulado: un diario completo con tres proyectos y uno privado produjo 12 peticiones sin enviar su contenido al modelo externo; un modelo mentiroso en todos los intentos (IDs inventados en extracción/plan y cifra inventada en síntesis) produjo un informe mecánico con los 10 resultados y ninguna sección inválida. La reproducción de R2-01 recorrió captura → paquete → HTTP: ambos modelos recibieron la contraseña SMTP sintética conocida y el JSON publicado la conservó. Scripts de reproducción de esta sesión: `/tmp/phase2_review_repro.py`, `/tmp/phase2_review_wire.py` y `/tmp/phase2_review_adversarial.py`; ejecutar con `PYTHONPATH=$PWD .venv/bin/python <script>`.

Tras las correcciones, se muestrearon cinco afirmaciones de un diario completo de fixtures (semilla `20261105`): sus referencias apuntaban a evidencias no vacías de métricas, notebook, documentación y rama Git. El doble HTTP redacta la afirmación genérica «Hay evidencia disponible para contrastar», respaldada en esos casos; esta muestra comprueba trazabilidad e integración, sin demostrar calidad científica. La comprobación de cinco afirmaciones de un informe real permanece expresamente pendiente en la firma humana.

## Firma de la persona

Comprobaciones que solo puedes hacer tú:

- [ ] En una muestra de 5 afirmaciones de un informe real, todas se sostienen al abrir sus evidencias
- [ ] El plan de mañana es ejecutable: cada tarea tiene acción y criterio de finalización claros
- [ ] El informe semanal de prueba aporta algo que no estaba en los diarios

- [ ] Apruebo la fase


## Cambio posterior de requisito (D-047)

Después de esta revisión, la persona rechazó sustituir secciones no validadas por
contenido mecánico y solicitó una construcción modular y jerárquica. El veredicto
técnico de arriba se conserva como registro del alcance anterior; no acredita el
cumplimiento del nuevo requisito. La fase permanece abierta y necesitará revisión
de la implementación propuesta en [HIERARCHICAL_DIGEST.md](../HIERARCHICAL_DIGEST.md)
antes de solicitar su firma. Los jobs de validación 7 y 8 se detuvieron sin envío.
