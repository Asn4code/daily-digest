# Revisión independiente de timestamps de procedencia

reviewer: codex, sesión independiente (`review_watchlist_hierarchy`)
date: 2026-11-16
scope: delta de `digest.llm.validator` posterior a `1e0ec14`

Esta ficha no modifica la aprobación técnica de WA-11 ni sus firmas humanas.

## Hallazgos

- **Importante, corregido y revalidado:** el primer reconocimiento estricto del
  timestamp permitía que variantes no reconocidas cayeran al análisis antiguo por
  componentes. Con
  `event_at=2026-11-09T10:04:32+00:00` y
  `observed_at=2026-11-16T13:08:23+00:00`, una afirmación que mezcla fecha de
  evento y hora observada se rechazaba con `2026-11-09T13:08:23Z`, pero se aceptaba
  con `2026-11-09t13:08:23Z`, `2026-11-09T13:08:23` o
  `2026-11-09T13:08:23Zobservada`. Era una limitación previa, no una regresión
  introducida por este delta. Ahora el reconocimiento de tokens con fecha,
  `T`/`t` y hora impide volver al análisis por componentes: el token debe tener
  formato válido y respaldo conjunto, o se rechaza. Las tres reproducciones se
  rechazan y también un sufijo que intenta incorporar una medida científica.
  Reproducción: `build/review-wa11/test_timestamps.py`, prueba parametrizada
  `test_mixed_timestamp_cannot_fall_through_to_independent_date_and_clock`.

## Comprobaciones

- Las 91 pruebas compartidas finales de `test_provenance_timestamps.py` y
  `test_llm_validation.py` pasan. Incluyen timestamps
  completos exactos, equivalencia `Z`/`+00:00`, fracciones exactas, mezcla de
  metadatos, cambios de hora/offset y evidencia no citada.
- Las pruebas privadas confirman que una cita literal completa con offset propio
  se acepta y cambiar su offset se rechaza; un timestamp válido no permite añadir
  una cifra y unidad científicas ajenas a las fuentes.
- La comparación conserva exactamente offset y precisión. Solo normaliza la
  forma `T`/`t`, `Z`/`z` y `Z` respecto a `+00:00`; no convierte instantes entre
  zonas ni autoriza combinar metadatos de entradas citadas diferentes.
- Ejecución final independiente: **98 pruebas pasan** (91 compartidas y 7
  privadas), con el comando siguiente. No cambian la validación de IDs, cifras
  ni unidades y la clave de caché ya incorpora el contenido del validador.

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/unit/test_provenance_timestamps.py tests/unit/test_llm_validation.py build/review-wa11/test_timestamps.py
```

## Veredicto

**Aprobada técnicamente** para este delta, sin hallazgos bloqueantes ni
importantes abiertos. No se emplearon proveedores reales ni se modificaron
producción, pruebas compartidas o firmas desde esta sesión. Esta revisión no
aprueba el ensayo real ni declara completo un informe pendiente.
