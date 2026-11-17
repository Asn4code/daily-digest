# Revisión independiente de una muestra privada de seguimiento

reviewer: codex, sesión independiente (`review_watchlist`)
date: 2026-11-17
verdict: cambios

## Alcance exacto

Artefacto privado `build/phase3-live/watch-only-df030f5af16d47bf84c0d2c8464c3f0d.json`,
SHA-256 `43791c24fb803254fbab91e85c188515f618c77ba2fc6a038e6f6177e6e61e97`.
Contiene evaluaciones de seguimiento y sus cotejos; no es un informe completo.

La ventana es **9 de noviembre de 2026, 05:00–16:00 UTC**. Las evidencias se
observaron el 16 de noviembre; las preguntas humanas se guardaron ese día y se
aplicaron retrospectivamente. Esta muestra no describe el estado actual.
No se aprueba la fase, el informe completo ni la comprensión humana.

Esta versión pública conserva los hallazgos sin reproducir datos científicos
de los proyectos. La ficha íntegra permanece en el archivo privado
`build/review-watchlist-real/watchlist-real-sample-full.md`, con los campos,
referencias y detalles exactos de cada caso.

## Hallazgos

**R1 — Bloqueante para aceptar la muestra: requisito trasladado entre acciones.**
Un campo `limits` atribuye al cotejo de resultados existentes una aprobación
previa de cambios de protocolo que la fuente exige para recuperar otros
resultados. La fuente distingue ambas acciones y no establece esa dependencia
para el cotejo. La evaluación introduce un requisito que puede bloquear
injustificadamente la comprobación propuesta. Debe conservar las decisiones por
separado. Regresión propuesta: compartir documento o referencias no autoriza
trasladar requisitos de regeneración a la comparación de resultados existentes.

**R2 — Importante: ausencia de registro convertida en inexistencia del resultado.**
Un campo `meaning` empieza indicando correctamente que la comprobación no consta
ejecutada en las evidencias del intervalo, pero termina afirmando que su
resultado no existe todavía. Otro campo `limits` reconoce que la cobertura
parcial impide afirmar exhaustivamente esa ausencia; los paquetes tienen
`coverage_complete: false`. La conclusión admisible es que **el resultado no
consta en las fuentes disponibles para esa ventana**, no que no exista.
Regresión propuesta: una comprobación declarada pendiente con cobertura parcial
no autoriza afirmar la inexistencia de resultados fuera de lo observado.

**R3 — Importante: plan futuro presentado como certeza y exclusión añadida.**
Un campo `limits` convierte en certeza futura un plan pendiente de aprobación
y le atribuye excluir un método que la fuente no declara excluido. La fuente
solo registra un paquete preparado y pendiente de entrega a otra persona; eso
no constituye una decisión sobre su exclusión del plan. Debe distinguir lo
previsto por el plan del estado separado del paquete externo, sin decidir su
alcance futuro. Regresión propuesta: preparación y entrega pendiente no
equivalen a una exclusión aprobada; un plan no anticipa su ejecución final.

**R4 — Importante: alcance insuficientemente acotado de resultados ilegibles.**
Un campo `limits` describe resultados no legibles localmente sin restringir qué
casos y métodos presentan el problema. La fuente identifica un subconjunto
enumerado con diferencias entre métodos; no declara ilegible el grupo completo.
Debe conservar ese alcance o remitir explícitamente a la lista pertinente.
Regresión propuesta: el fallo de lectura de un subconjunto no se generaliza al
grupo completo.

## Comprobaciones y aspectos conservados correctamente

- Se revisaron todos los campos de las evaluaciones, incluidos `finding`,
  `meaning`, `limits`, `next_check` y sus referencias. La matriz preparatoria
  permanece en `build/review-watchlist-real/checklist.md`.
- Las evidencias y preguntas fijadas coinciden exactamente con el inventario
  original ya cotejado. Los diffs completos y commits se comprobaron contra Git;
  las notas, contra sus snapshots. No se ejecutó contenido de los proyectos ni
  se escribió en ellos.
- Se conservan correctamente los casos documentados, las magnitudes citadas y
  parte de las restricciones de uso; no se inventa una métrica comparativa ya
  calculada. `next_check` propone comprobaciones pendientes sin afirmar que el
  servicio las ejecutó. Los detalles científicos permanecen en la ficha privada.
- Se distingue la decisión humana comunicada de la ejecución: los campos
  pertinentes conservan que falta aprobación y que no constan registros de
  ejecución del trabajo nuevo. El siguiente paso no ejecuta ni acepta trabajo.
- Con el código de `2619df0`, `validate_report` pasa y los `check:watch` contienen
  `approved: true`. Los hallazgos son errores semánticos que esas comprobaciones
  no detectaron. `require_complete` rechaza el artefacto porque siguen pendientes
  secciones ajenas al alcance reducido. Esta revisión no elimina pendientes ni
  publica nada.

## Reproducción privada

`.venv/bin/python build/review-watchlist-real/reproduce_sample_findings.py`
muestra los campos exactos y sus fuentes. El script comprueba primero la huella
del artefacto y no lo modifica. La ficha íntegra privada conserva las rutas de
campos JSON y las referencias para reproducir R1–R4. Estos archivos privados no
se incorporan al repositorio público.

## Veredicto

**Cambios.** Las evaluaciones no se aceptan todavía como muestra científica
validada. Deben repararse y volver a cotejarse, preservando esta candidata y su
procedencia. Las referencias válidas y los cotejos positivos no bastan para
aprobar las transposiciones de alcance, las dependencias añadidas ni las
afirmaciones categóricas detectadas. No se modifica ninguna firma humana.

## Revisión de la mitigación propuesta, 17 de noviembre

Se revisaron `watchlist.md` versión 3 y la nueva capa `grounding_watchlist.md`
versión 1. Cubren R1–R4: asignan cada requisito a su acción, distinguen ausencia
de registro de inexistencia con cobertura parcial, condicionan los planes,
evitan deducir exclusiones desde entregas pendientes y conservan el alcance de
los subconjuntos. Las reglas abarcan todos los campos sin exigir repeticiones
innecesarias. El constructor añade la capa al cotejo general de `WatchAssessment`.

Los casos de `tests/integration/test_watchlist_fidelity.py` pasan. Con un doble
determinista comprueban bloqueo o reparación de una condición trasladada y que
una revisión de la capa de cotejo reaudita candidatos en caché sin volver a
generarlos. Prueban el flujo; no demuestran que un proveedor real detecte todos
los errores semánticos.

La mitigación resulta pertinente como instrucción y conserva el bloqueo por
cotejo negativo. **La candidata con la huella anterior continúa rechazada.**
Solo una muestra nueva e identificada puede demostrar si la corrección funciona
en las evaluaciones reales; deberá cotejarse de nuevo contra los originales.
