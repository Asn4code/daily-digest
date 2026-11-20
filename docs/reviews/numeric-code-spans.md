# Revisión independiente del formato numérico en código literal

reviewer: codex, sesión independiente (`review_watchlist_hierarchy`)
date: 2026-11-20
scope: delta de `quantities.view` posterior a `53330f1`, con protección de entidades y controles

Los ejemplos son sintéticos. Esta revisión no aprueba una muestra real, la
capacidad científica del proveedor ni firmas de fase.

## Diagnóstico y hallazgo corregido

Una fuente como `Identificador SRR123_456` con el identificador en código literal
activaba el fallback de formato ambiguo para toda la fuente. Eso impedía
normalizar otro fragmento independiente, `3 partial`, cuando su etiqueta también
estaba entre backticks. El valor y la etiqueta estaban respaldados.

La primera propuesta de comparar únicamente dos contadores no era segura.
En ``1*2*3 y `&#1*2;`.`` —el segundo fragmento como código inline—,
`html.unescape` elimina el control de la referencia malformada y borra su trigger.
El trigger exterior puede entonces compensar el recuento del código literal:
los contadores coinciden aunque quede formato numérico ambiguo fuera del código.
Normalizarlo produciría el valor nuevo `123`. También se reprodujo con las
variantes `&#01*2;` y `&#x1*2;`.

**Bloqueante, corregido y revalidado:** la propuesta sin protección se descartó
antes de producción. En la variante revisada, si decodificar entidades cambia
cualquier contenido de código inline, se conserva
el fallback anterior cuando hay un trigger global. La comparación usa ocurrencias
con multiplicidad, no un conjunto de coincidencias. Se parsea el Markdown
original; no se fabrican spans de código decodificando sus delimitadores.

## Variante revisada

- Solo se normaliza el resto cuando todos los triggers están cubiertos por los
  contenidos literales y la protección de entidades lo permite. No se eliminan
  operadores o guiones bajos del código ni se escapan o duplican sus backslashes.
- Las diferencias de normalización de código, como un salto de línea convertido
  en espacio por Markdown, pueden mantener el fallback conservador. Esta revisión
  no exige aceptar todos los casos multilínea o con entidades.
- El control previo al parseo conserva caracteres `Cf` y `Cc` prohibidos para
  que el analizador numérico los rechace. Así Markdown no puede reemplazar un NUL
  y ocultar una unidad añadida. Nueva línea, retorno y tabulación mantienen el
  tratamiento de espacios existente.
- No cambian la comparación de cantidades, unidades, referencias, relaciones,
  anotaciones o procedencia. La caché ya incorpora el contenido de `quantities.py`
  y revalida sus piezas; los originales, hashes y citas permanecen intactos.

## Comprobaciones independientes

**365 pruebas focalizadas pasan**: 345 compartidas y 20 privadas. Las privadas
incluyen ocurrencias repetidas e idénticas dentro/fuera de código, triggers
solapados, entidades malformadas, delimitadores codificados o escapados, backticks
de diferente longitud, saltos de línea, backslashes literales y controles con otra
fórmula válida en el mismo campo. También se ejecutaron las regresiones de
dimensiones, cantidades, identidades, timestamps, caché, fuentes extensas y cotejo.

```bash
PYTHONPATH=. .venv/bin/pytest -q --import-mode=importlib build/review-code-spans/test_guarded_code.py tests/unit/test_numeric_code_spans.py tests/unit/test_quantity_context.py tests/unit/test_source_identifiers.py tests/unit/test_provenance_timestamps.py tests/unit/test_llm_validation.py tests/unit/test_node_cache.py tests/integration/test_source_pipeline.py tests/integration/test_grounding.py
```

`build/review-code-spans/counter_diagnostic.py` conserva la reproducción privada
de la propuesta insegura. No es código de producción.

## Veredicto

**Aprobada técnicamente la variante con ambas protecciones**, sin hallazgos
bloqueantes o importantes abiertos en el delta revisado. No hay nuevas
dependencias, lecturas de proyectos, límites, reintentos, formatos humanos o
estados de revisión. El cotejo semántico y la validación humana siguen siendo
necesarios para la muestra exacta; la instrucción de formato no acredita su éxito.

No se ejecutaron proveedores reales ni se modificaron producción, pruebas
compartidas, tablero, commits o firmas desde esta revisión. La suite completa y
la puerta ejecutadas por el constructor no se atribuyen a esta sesión.
