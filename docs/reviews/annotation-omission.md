# Revisión independiente de omisión de notas numéricas

reviewer: codex, sesión independiente (`review_watchlist_hierarchy`)
date: 2026-11-19
scope: commit `3b98404`, delta de `quantities.py` y `validator.py` posterior a `3617f4f`

Esta ficha complementa `wa-12.md` sin modificar su aprobación anterior. No
aprueba una candidata o informe real, el estado del trabajo 4 ni firmas humanas.

## Problema y cambio revisado

En un ejemplo sintético equivalente, el fragmento `12 de 12` no añade una
cantidad ni unidad a `12 de 12 (PDB_ID terminó tras…)`, pero la igualdad de toda
anotación lo rechazaba. El nuevo contraste permite omitir determinadas notas
simples. Si la candidata afirma una nota, debe conservarla completa. Siguen
coincidiendo valores, unidades, operadores y aridad; todas las notas afirmadas
en la relación deben corresponder a una misma fuente citada.

Las anotaciones son tuplas internas, sin modificar el esquema de los informes.
La posibilidad de omitir una nota no convierte `None` en un comodín de unidades,
valores u operadores ni permite construir relaciones con fuentes distintas.

## Hallazgos corregidos y revalidados

- **Bloqueante:** la primera versión permitía perder dimensiones anidadas, como
  `((nm))`, `([nm])`, `((/ nm))` y `(PDB_ID (nm))`. Se conserva el rechazo de su
  omisión y de formatos anidados ambiguos.
- **Bloqueante:** los delimitadores Unicode `（nm）` y `【nm】` dentro de una nota
  eludían el examen de paréntesis ASCII. El control usa las categorías Unicode
  de apertura/cierre, sin convertir caracteres mediante NFKC ni reinterpretar IDs.
- **Bloqueante:** expresiones como `|nm|` o `≡ nm`, incluso detrás de un PDB,
  quedaban clasificadas como no dimensionales. También sucedía con `en nm`.
  La elegibilidad de la omisión rechaza notación matemática no soportada,
  cualificación dimensional, unidades físicas sin cantidad ligada y formato
  literal residual. Los símbolos monetarios, modificadores y otros símbolos
  ambiguos tampoco autorizan eliminar la nota.
- Inspeccionada y revalidada la corrección adicional del constructor: enlazar
  operandos ya no reactiva unidades inválidas como `<unbalanced>` o `<nested>`.

Las reproducciones independientes están en
`build/review-wa12/test_annotation_omission.py`: **13 pruebas pasan**. Incluyen
el ratio literal sin procedencia y los rechazos dimensionales anteriores. Se
mantienen también los ataques de paréntesis de la propuesta retirada y las
regresiones de anotaciones sustituidas o mezcladas.

## Comprobaciones y límites

Ejecución final independiente: **429 pruebas focalizadas pasan**, con cantidades,
IDs, timestamps, pruebas privadas actuales e históricas, fuentes extensas, caché,
grounding y seguimiento E2E. Comando reproducible:

```bash
PYTHONPATH=. .venv/bin/pytest -q --import-mode=importlib tests/unit/test_quantity_context.py tests/unit/test_source_identifiers.py tests/unit/test_provenance_timestamps.py tests/unit/test_llm_validation.py build/review-wa12/test_annotation_omission.py build/review-wa12/test_adversarial.py build/review-wa11/test_structure_parentheses.py build/review-wa11/test_source_identifiers.py build/review-wa11/test_timestamps.py tests/integration/test_watchlist_fidelity.py tests/e2e/test_watchlist.py tests/unit/test_node_cache.py tests/integration/test_source_pipeline.py tests/integration/test_grounding.py
```

El cotejo sigue recibiendo las fuentes completas y sus condiciones. Una nota
admisible para omisión en el contraste numérico puede contener alcance,
incertidumbre o un control decisivo para interpretar el resultado: este cambio
no autoriza perderlos en el informe. Esa comprobación semántica y la revisión
humana conservan su función. Los formatos ambiguos pueden quedar pendientes.

La vista derivada conserva originales, hashes y citas literales. Los cambios de
estos dos módulos forman parte de la huella del validador en la caché y sus
salidas se revalidan. No cambian privacidad, fuentes permitidas, límites,
reintentos, formatos humanos, estados de revisión ni condiciones de publicación.
No se introducen dependencias o DDL.

## Veredicto

**Aprobada técnicamente** para el delta revisado, sin hallazgos bloqueantes ni
importantes abiertos. Esta comprobación focalizada no sustituye la suite completa,
la puerta automática o la validación del informe real y humana.

Desde esta revisión solo se modificaron pruebas privadas y esta ficha. No se
editaron producción, pruebas compartidas, tablero, commits ni firmas, y no se
emplearon proveedores reales.
