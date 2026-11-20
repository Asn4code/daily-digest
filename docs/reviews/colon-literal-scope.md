# Revisión independiente de citas con dos puntos

reviewer: codex, sesión independiente (`review_watchlist_hierarchy`)
date: 2026-11-20
scope: prompt `source` v13 y doce regresiones sobre el validador de `83d14ea`

Esta ficha usa ejemplos sintéticos. No aprueba una salida real ni firma una fase.

## Diagnóstico y decisión revisada

La fuente sintética `Lista (12 filas: modelo, id, estado).` se interpreta como
una cantidad con unidad interna `filas : modelo`. Por eso se rechaza `12 filas`
y se acepta el fragmento literal completo. No se introdujo una regla que elimine
los dos puntos ni clasifique cualquier palabra posterior como explicación.
Sin una clasificación estructurada de las cabeceras, esa heurística también
podría perder dimensiones o denominadores.

`source` v13 pide citar completo el paréntesis que contiene la cifra y su texto
tras dos puntos, sin recortar valor, unidad/etiqueta o anotación. Mantiene las
instrucciones de conservar controles, alcance, condiciones y cifras decisivas;
de no copiar tablas enteras ni esconder cifras para evitar la validación; y de
tratar las fuentes como datos no fiables. No autoriza aceptar globalmente citas
literales ni ocultar resultados.

## Comprobaciones independientes

- El diff de producción revisado contiene únicamente el cambio de prompt.
  `validator.py`, `quantities.py`, router, builder y caché permanecen iguales
  respecto al commit base. No cambian unidades, operadores, fuentes permitidas,
  privacidad, presupuestos, reintentos, estados humanos o publicación.
- El cargador reconoce `source 13 extract`; su cuerpo tiene 3629 caracteres.
  La versión y los mensajes forman parte de la clave de caché. Las variantes
  anteriores no se sobrescriben y esta revisión no modifica candidatas guardadas.
- **Doce regresiones pasan:** el fragmento completo y los literales de dimensiones
  y ratios se aceptan; los recortes de `Å: nm`, `12:20`, cantidades tras una
  unidad y dimensiones dentro de una lista se rechazan. También se rechazan
  cifras, etiquetas y dimensiones cambiadas. Los positivos comprueban que el
  paquete original permanece intacto.
- **Otras 29 pruebas pasan:** router, caché y recorrido de fuentes extensas,
  incluidos límites de mensajes y reparaciones. Total focalizado: **41 pruebas**.
  No se repitió aquí la suite completa ni la puerta automática.

```bash
.venv/bin/pytest -q tests/unit/test_quantity_context.py -k colon_fragment_does_not_drop_ambiguous_labels_dimensions_or_operands
.venv/bin/pytest -q tests/unit/test_llm_router.py tests/unit/test_node_cache.py tests/integration/test_source_pipeline.py
```

El diagnóstico privado original permanece en
`build/review-wa05/colon_diagnostic.py`. Imprime los resultados y las cantidades
interpretadas; las doce pruebas compartidas añaden aserciones verificables.

## Veredicto

**Aprobada técnicamente** esta indicación de redacción y sus regresiones, sin
hallazgos bloqueantes en el alcance revisado. La instrucción no demuestra que un
proveedor real la siga ni que una candidata completa conserve todas las condiciones
científicas: siguen siendo necesarios sus validadores y cotejos.

No se ejecutó un ensayo real ni se verificó su plazo de generación. La suite
completa, la puerta y la firma humana mantienen sus requisitos propios. Esta
sesión no modificó producción, pruebas compartidas, tablero, commits ni firmas.
