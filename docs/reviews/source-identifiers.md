# Revisión independiente de identificadores de fuente

reviewer: codex, sesión independiente (`review_watchlist_hierarchy`)
date: 2026-11-17
scope: delta de `digest.llm.validator` posterior a `8995f75`

Esta ficha conserva las revisiones de WA-11 y timestamps; no aprueba el informe
real pendiente ni sustituye las firmas humanas.

## Hallazgos

Los casos siguientes corresponden al primer delta. Todos están corregidos y
revalidados sobre la versión final examinada.

- **Bloqueante, corregido y revalidado:** un SHA íntegro solo numérico se elimina incluso
  cuando va seguido de una unidad física. Con `locator="1" * 40`, fuente de
  tipo `commit` y extracto sin cifras, se aceptan `Commit <SHA> nm.` y
  `El valor hash <SHA> nm.`. El valor desaparece antes de validar cantidades.
  Reproducción privada: `test_numeric_sha_followed_by_scientific_unit_cannot_hide_measurement`.
- **Bloqueante, corregido y revalidado:** las nuevas etiquetas `lote 1` y `batch 1` también
  se eliminan delante de una unidad. Una fuente que solo menciona `Pendiente
  lote 1. Resultado 3 Å.` permite `Resultado: lote 1 nm.`. La guardia de cifra
  anterior no protege el sufijo. Reproducción privada:
  `test_batch_identifier_cannot_hide_an_unsupported_measurement`.
- **Importante, corregido y revalidado:** `SHA-1: <SHA real>` y `SHA-256: <SHA real>` se
  rechazan si el extracto no contiene otras cifras. Se interpreta `1` o `256`
  de la etiqueta como cantidad tras retirar el identificador. La fuente de la
  prueba compartida incluye `lote 1`, lo que oculta el primer falso rechazo.
  Reproducción privada: `test_hash_algorithm_label_is_not_itself_a_measurement`.
- **Importante, corregido y revalidado:** un hash ajeno que empieza por letras, o uno solo
  alfabético, cae al análisis numérico sin producir tokens y se acepta. También
  ocurre con un hash abreviado alfabético. Son ejemplos `Commit ` seguido de
  cuarenta `f`, o `Commit abcdefabcdef` con un localizador íntegro más largo.
  La pertenencia a la fuente y la longitud deben comprobarse expresamente al
  reconocer la referencia, no mediante la aparición casual de una cifra.
  Reproducciones privadas: `test_unknown_full_hash_is_not_accepted_just_because_no_numeric_token_is_seen`
  y `test_alpha_only_shortened_identity_is_not_exempted`.

La corrección valida etiqueta e identidad juntas, exige un hash completo de
40 o 64 caracteres presente en el localizador de una evidencia `commit`/`diff`
citada y consume también el número del algoritmo de la etiqueta. Rechaza
referencias calificadas ajenas y abreviaciones desde cuatro caracteres. El
reconocimiento no se extiende a palabras de una a tres letras, para conservar
gramática como «commit de…»; no son abreviaciones Git válidas.

Las guardias de contexto conservan las cantidades y sus unidades: además de
`nm` directo, rechazan aperturas de paréntesis/corchetes, división, superíndices
y demás notación física tras la identidad. Las primeras correcciones todavía
permitían `<SHA> (nm)`, `<SHA> [nm]` y `<SHA> / nm`, y los mismos sufijos tras
`lote 1`; las pruebas privadas adicionales reprodujeron esos escapes y ahora
se rechazan. Los cuatro caracteres iniciales del hash tampoco bastan para
atribuir una identidad íntegra.

## Comprobaciones

- Las 103 pruebas compartidas de identificadores, timestamps y validación
  numérica pasan sobre el primer delta. Las pruebas privadas reproducen las
  carencias adicionales anteriores y rechazan un hash que solo aparece en una
  evidencia no citada: **11 fallan y 3 pasan** sobre ese delta.
- Inspección de pertenencia exacta a localizadores de `commit`/`diff`, extracción
  del hash antes del separador de ruta y necesidad de etiqueta explícita. No se
  consulta Git ni se ejecuta contenido para reconocer el identificador.
- Ejecución final independiente: **159 pruebas pasan** (134 compartidas de
  identificadores, timestamps y validación numérica; 25 privadas). Incluye
  identidades solo numéricas, hashes alfabéticos inventados, abreviaciones
  de cuatro a seis caracteres, etiqueta de algoritmo sin otras cifras,
  evidencia no citada, unidades físicas y decimales. La corrección permanece
  en el validador incorporado a la clave de caché; no añade dependencias ni
  permisos sobre proyectos.

```bash
PYTHONPATH=. .venv/bin/pytest -q --import-mode=importlib tests/unit/test_source_identifiers.py tests/unit/test_provenance_timestamps.py tests/unit/test_llm_validation.py build/review-wa11/test_source_identifiers.py
```

## Veredicto

**Aprobada técnicamente** para este delta, sin hallazgos bloqueantes ni
importantes abiertos. No se modificaron producción, pruebas compartidas ni
firmas desde esta sesión. Esta revisión no aprueba el informe real pendiente
ni sustituye la suite completa o las comprobaciones humanas.
