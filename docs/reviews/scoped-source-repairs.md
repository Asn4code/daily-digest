# Revisión independiente de la reparación acotada por afirmación

reviewer: antigravity, sesión independiente (`research` subagent, primera pasada + revalidación)
date: 2026-11-20
scope: implementación de `docs/SCOPED_SOURCE_REPAIRS.md` en `src/digest/llm/source_repair.py`, `src/digest/llm/client.py`, `src/digest/llm/router.py`, `src/digest/report/builder.py`, `tests/fixtures/llm.py` y `tests/unit/test_scoped_source_repairs.py`

Esta revisión no sustituye la comprobación sobre muestra real ni las firmas de fase.

## Hallazgos iniciales y resoluciones verificadas

En la primera pasada independiente no se encontraron hallazgos bloqueantes; se detectaron **2 hallazgos importantes** y **4 menores**, todos resueltos y revalidados en sesión independiente nueva:

- **Importante, resuelto (`src/digest/llm/source_repair.py`):** en tres combinaciones (`unknown_evidence` + HTML en la misma afirmación, más de 20 errores previos + HTML en posición 21+, o HTML dentro de `evidence`/`result_id`), el blanqueado selectivo por `target.issues` conservaba el HTML en `wire_targets`. Se sustituyó por `_blank_html` con el mismo patrón de `validator.py` aplicado recursivamente sobre todo el contexto enviado (`wire_targets`, inicialmente sobre toda la candidata y posteriormente compactado solo a los objetivos rechazados para caber bajo `SOURCE_PACKET_CHARS = 24_000`), conservando intacto `self.candidate` para la reconstrucción y la validación posterior.
- **Importante, resuelto (`tests/fixtures/llm.py`):** `fake_response` carecía de rama para `SourceClaimRepair`, lo que podía fallar si una prueba de integración inyectaba un error reparable en un paquete con presupuesto disponible. Se añadió soporte completo para `SourceClaimRepair`, distinguiendo `Claim` e `Interpretation`.
- **Menor, resuelto (`src/digest/llm/source_repair.py`, `src/digest/llm/router.py`, `src/digest/report/builder.py`):** `plan_source_repair` heredaba únicamente `MAX_SCHEMA_CHARS` y no `max_schema_chars` calculado por `builder.py` (`schema_limit`). Ahora `Router.generate` acepta `max_schema_chars`, `builder.py` pasa `schema_limit`, y `plan_source_repair` comprueba el límite tanto en `evidence_schema` como sobre `json.dumps(repair_schema, ensure_ascii=False)`.
- **Menor, resuelto (`src/digest/llm/source_repair.py`):** `_claim_path` no acotaba el rango en los índices de `evidence` (profundidad 3/4). Se añadió comprobación explícita de entero no booleano dentro de `0 <= ev_index < len(refs)`.
- **Menor, documentado (`src/digest/llm/validator.py`):** si una salida combina `result_id` inválido con un error en una afirmación, `validator.validate` lanza primero el error de la afirmación antes de comprobar `result_id`. No se relaja ni modifica `validator.py` para preservar la huella y la seguridad: en el reintento el parche acotado sigue rechazado por `unknown_result` y pasa al respaldo o queda pendiente, sin aceptar un `result_id` inválido.
- **Menor, resuelto (`docs/` y `tests/unit/test_scoped_source_repairs.py`):** ampliadas las pruebas con los tres casos de HTML, `added_annotation`, claves duplicadas anidadas y Unicode, `NaN`/`Infinity`, límites de `max_schema_chars`, rangos de `evidence`, comprobación de `llm_call`/`nodes/` tras rechazo de `apply()` y prueba de `fake_response`.

## Verificación de revalidación independiente

- **Contratos cerrados y parseo JSON:** `_unique_object` en `src/digest/llm/client.py` rechaza claves duplicadas en raíz, objetos anidados y colisiones por escapes Unicode con `ClientError("invalid_json")`. `SourceClaimRepair` (`Output` con `extra="forbid"`, `strict=True`, `allow_inf_nan=False`) rechaza IDs ajenos, omitidos, `Claim` vs `Interpretation`, `result_id` o `SourceFindings` completos, `NaN`/`Infinity` y tipos inválidos. Los códigos de diagnóstico en `llm_call.error` usan el esquema base (`<extra>`), sin filtrar claves ni valores.
- **Privacidad, presupuesto y caché:** `redact_tree` sanea antes de planificar y antes de reconstruir; `external_allowed = false` restringe inicial y reparación a `internal`; `max_message_chars` mide `[*messages, *repair_plan.messages]` completo; `nodes/` almacena únicamente `SourceFindings` completo tras `validate()` y `GroundingAudit` sigue ejecutándose íntegro sobre el resultado reconstruido.
- **Comandos de la sesión revalidatora:**
  - `.venv/bin/ruff check --no-cache src tests` → `All checks passed!`
  - `.venv/bin/ruff format --check --no-cache src tests` → `164 files already formatted`
  - `.venv/bin/mypy --no-incremental --cache-dir=/dev/null src` → `Success: no issues found in 93 source files`
  - `.venv/bin/pytest -p no:cacheprovider -q tests/unit/test_scoped_source_repairs.py tests/unit/test_llm_router.py tests/integration/test_source_pipeline.py` → `43 passed in 10.81s`
  - `.venv/bin/pytest -p no:cacheprovider -q tests/unit/test_llm_validation.py tests/unit/test_node_cache.py tests/e2e/test_llm_report.py` → `96 passed in 14.31s`
  - Sondas adversariales en memoria (`ALL_ADVERSARIAL_CHECKS_PASSED`, `ALL_FALLBACK_AND_SCHEMA_LIMIT_CHECKS_PASSED`, `FORBIDDEN_RULES_CLEAN`).

## Veredicto

**Aprobada técnicamente la implementación de reparación acotada por afirmación**, incluida la compactación a `wire_targets` revalidada en sesión independiente nueva (`43 passed` focalizadas, `96 passed` de regresión, `ruff`, `mypy` y sondas adversariales limpias), sin hallazgos bloqueantes, importantes ni menores abiertos en el código revisado. Esta aprobación técnica cubre el contrato y los invariantes del código; la auditoría científica sobre una candidata real exacta se registra por separado en `docs/reviews/phase-3.md` y `docs/DECISIONS.md` (D-071).

## Ampliación: guardia anti-evasión (`B1`) y prompts `source` v14 / `grounding` v10 (2026-11-20)

Tras rechazar la auditoría científica de la primera candidata real el borrado de cifras en el parche (`B1`) y cuatro incidencias de alcance/procedencia (`I1–I4`), se añadió en `src/digest/llm/source_repair.py` el control determinista de conservación numérica (`_source_numbers` acotado por objetivo a sus IDs citados en `evidence` y comprobando metadatos `metric` con independencia de marcadores en extractos, `required_values` / `requires_quantity`, `preserve_numbers` en `wire_targets` y bloqueo en `SourceRepairPlan.apply()` si un parche omite valores respaldados), junto con `source` v14 y `grounding` v10.

- La primera revisión técnica independiente del cambio (`bb2beff0`) detectó casos límite sobre el alcance por objetivo de `_source_numbers` y el orden de lectura de metadatos `metric`; todos quedaron resueltos.
- La sesión revalidatora independiente (`627bde2b`) emitió veredicto **APROBADA TÉCNICAMENTE** sin hallazgos bloqueantes ni importantes (`38` pruebas focalizadas, `375 + 32` de regresión, `ruff` y `mypy` limpios); un ajuste menor posterior en dos líneas de `source.md` y el orden de lectura en `source_repair.py` mantuvo las `38 passed in 10.12s` focalizadas antes de la batería final completa (`make check`).
- La auditoría científica independiente posterior sobre el ensayo real `build/phase3-live/source-only-7c83984d37c545619052ecb398f0688b.json` (`b1dc0fb5`, **aprobada**, 0 bloqueantes, 0 importantes, 5 menores) dejó constancia de una salvedad menor cuando un número ajeno del título de contexto coincide solo por valor numérico con una cifra homónima en la evidencia citada.
