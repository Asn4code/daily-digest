# Revisión independiente de PDB tras un recuento

reviewer: codex, sesión independiente (`review_watchlist_hierarchy`)
date: 2026-11-17
scope: propuesta de excepción de `validator.structure` posterior a `b95c724`, retirada sin commit

Esta ficha revisa exclusivamente la excepción del identificador PDB, sin aprobar
la candidata completa ni cambiar las revisiones o firmas anteriores.

## Hallazgos

- **Bloqueante en la propuesta retirada:** la asociación literal `206 (9WKV_A` permite eliminar
  el identificador aunque el recuento se use como operando de una fórmula ajena.
  Con fuente `Completo, 206 de 206 (9WKV_A terminó tras ~6 h de CPU). RMSD 1.4 Å.`,
  se aceptan `RMSD: 1.4 / 206 (9WKV_A).` y las variantes con `*` y `+` separados
  por espacios. La guarda solo excluye operadores adyacentes al recuento.
- **Bloqueante en la propuesta retirada:** el mismo caso permite cantidades con una unidad
  física no respaldada, porque el paréntesis separa recuento y unidad: se aceptan
  `RMSD: 206 (9WKV_A) nm.` y `RMSD: 206 (9WKV_A nm).`.

Reproducciones privadas en
`build/review-wa11/test_structure_parentheses.py::test_parenthetical_identity_does_not_authorize_operator_or_unit`.
La propuesta aceptaba el caso literal válido. Resultado del primer delta: cinco fallos
privados y una prueba positiva que pasa.

## Retirada y comprobación

El constructor retiró íntegramente la excepción, sin incorporarla a un commit.
La comprobación independiente siguiente devuelve código cero y ningún diff:

```bash
git diff --exit-code b95c724 -- src/digest/llm/validator.py tests/unit/test_source_identifiers.py
```

Sobre el código restaurado, las cinco reproducciones negativas se rechazan y
pasan. La prueba positiva del recuento con PDB entre paréntesis vuelve a fallar:
se conserva expresamente ese rechazo conocido, sin ampliar el permiso para
interpretar identificadores como cantidades. Esta ejecución diferencia la
retirada de una corrección que hubiera autorizado el caso literal.

```bash
PYTHONPATH=. .venv/bin/pytest -q build/review-wa11/test_structure_parentheses.py
```

## Revisión adicional de `source` v10

La revisión independiente del cambio posterior de prompt y `docs/LLM.md` no
encuentra autorización para perder controles, alcance o resultados. Se mantienen
las instrucciones de conservar condiciones y límites decisivos; el añadido exige
explícitamente conservar los controles que cambian la interpretación y prohíbe
omitir cifras decisivas o escribirlas con palabras para evitar la validación.
Los fragmentos numéricos mínimos deben preservar valor, unidad/etiqueta y
condición. Separar un recuento del identificador en oraciones permite expresar
ambos hechos; no concede una excepción para la cantidad o el identificador.

Evitar transcribir tablas enteras no cambia el inventario determinista de
evidencias y resultados ni las condiciones de completitud. Los originales siguen
disponibles y cada afirmación conserva sus citas. La redacción breve no garantiza
por sí misma una extracción suficiente: toda candidata posterior debe superar
los mismos validadores y cotejos, sin ocultar resultados del intervalo.

Comprobado que el cargador reconoce `source 10 extract` y que la clave de caché
incorpora mensajes y versión de prompt. La versión anterior conserva sus
artefactos; no se modifica texto humano. Una nueva comprobación del diff del
validador y sus pruebas respecto a `b95c724` sigue vacía.

**Cambio de prompt aprobado técnicamente**, sin hallazgos en ese alcance. No se
generó ni aprobó una candidata o informe completo durante esta revisión.

## Veredicto

**Propuesta descartada por insegura.** No queda ningún delta de esta excepción
en producción. Se conserva la aprobación técnica previa del código `b95c724`;
esta ficha no aprueba la candidata completa ni resuelve el rechazo literal
conocido. No se modificaron producción, pruebas compartidas, commits ni firmas
desde esta sesión y no se utilizaron proveedores reales.
