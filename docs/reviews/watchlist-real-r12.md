# Revisión independiente de seguimiento: borrador histórico r12

reviewer: codex, sesión independiente (`review_watchlist`)
date: 2026-11-24
verdict: aprobación limitada de una evaluación; cambios en la otra

## Alcance

Artefacto privado
`build/in11-validation/data/drafts/preview/rep_preview_2026-11-09_r12/draft.json`,
SHA-256 `3018fb525c520e695bf450e2c810d5c84e10d65a08c6dfde440b560553b0ec0b`.
Se revisaron todos los campos y referencias de sus evaluaciones de seguimiento,
no las demás secciones del informe.

La ventana es **9 de noviembre de 2026, 05:00–16:00 UTC**. Las preguntas y las
evidencias fijadas coinciden con el inventario original ya cotejado. Esta
revisión no describe el estado actual ni verifica nuevas ejecuciones. Los
detalles científicos permanecen fuera del repositorio público.

## Evaluación A: aprobada dentro del alcance histórico

La evaluación sobre una comparación pendiente conserva que el resultado no
consta en las fuentes disponibles, sin afirmar que no exista. Distingue el
estado de verificación de una métrica ya obtenida y mantiene la restricción
documentada de uso. El siguiente paso es una comprobación propuesta, con sus
alternativas, sin añadir requisitos de otra acción ni universalizar una
condición de una rama. No quedan hallazgos materiales abiertos en esta sección.

## Evaluación B: requiere cambios de alcance

**W12-S1 — Importante: omisión de una condición decisiva del plan citado.** El
hallazgo presenta el objetivo global comunicado y la ampliación prevista, pero
ningún campo conserva las excepciones por método y caso que el propio plan
establece. La única limitación retenida es la aprobación pendiente. Esa condición
administrativa no sustituye las restricciones técnicas de cobertura de la
ampliación, relevantes para la pregunta de seguimiento.

Las cifras describen un objetivo, no cobertura obtenida: **no se detecta una
afirmación de ejecución completada ni se atribuye falsamente cobertura total**.
El problema es que falta delimitar el alcance previsto. Una breve precisión
sobre las excepciones documentadas basta; no hace falta repetir tablas ni
inventar nuevos análisis o umbrales.

La evaluación sí conserva correctamente que el lanzamiento no está acreditado,
que la aprobación sigue pendiente y que comprobarla constituye un siguiente
paso propuesto. Tampoco añade una exclusión futura sin respaldo ni generaliza
un fallo de lectura de un subconjunto al conjunto entero. Esas correcciones no
eliminan W12-S1. La evaluación necesita otra candidata que conserve la condición
omitida antes de aceptarse científicamente.

## Verificación y reproducción privada

`validate_report` pasa y los cotejos automáticos de seguimiento están aprobados.
`require_complete` rechaza el borrador, como corresponde: otras secciones siguen
pendientes. Pasar esas comprobaciones no detectó la omisión de alcance anterior.

El cotejo exacto, con identificación de las secciones, campos, fuentes y textos,
está en `build/review-watchlist-real/review-watchlist-r12.json`, SHA-256
`d8803e08a8f897d2d54f00a54cf6c50eed1fc6fa9dba00f5b6826a102c5a00bc`.
Allí puede reproducirse la comparación entre `finding` y `limits` de la segunda
evaluación y las excepciones de su plan citado, sin publicar datos del proyecto.

## Veredicto limitado

Se aprueba exclusivamente la evaluación A de este artefacto histórico. La
evaluación B requiere cambios por W12-S1. **No se aprueban el informe completo,
las demás fuentes, la fase, una entrega ni la comprensión humana.** No se
modificó el artefacto, el corpus, los proyectos, producción, pruebas compartidas,
tablero, estados humanos ni firmas. Las candidatas anteriores conservan sus
veredictos independientes.

## Revisión limitada de la mitigación W12-S1

Se revisó `grounding_watchlist` v2, SHA-256
`dda85c52dd0d0f3edcc345ef84dd5f376c2c66bef1e9badc1bdb71cc867f4f89`.
La nueva instrucción exige conservar excepciones explícitas del plan por método,
caso o secuencia, aunque se describa correctamente un objetivo propuesto sin
afirmar ejecución. Una aprobación pendiente no sustituye esas excepciones.
También exige comprobar todos los campos antes de marcar una omisión, sin
obligar a repetir la condición en cada uno.

La mitigación es pertinente para W12-S1. No cambia `watchlist` v3 ni el contrato
de generación: permite conservar candidatas de generación y reauditar su caché
con la nueva capa; un rechazo utiliza la reparación ya existente.

La ejecución independiente previa de
`tests/integration/test_watchlist_fidelity.py` dio **16 pruebas correctas**.
Se inspeccionó además la modificación definitiva del caso nuevo: la candidata
solo expresa que la aprobación sigue pendiente, sin afirmar que sea el único
límite. Representa así una omisión implícita de las excepciones; el doble
devuelve `missing_condition`, con `field: []`, y cita las exclusiones de la fuente.
Comprueba bloqueo o reparación y que una revisión de cotejo reevalúa candidatos
cacheados sin otra llamada de generación cuando ya existe la reparación válida.
La reejecución de esta modificación corresponde al constructor. El transporte
sigue siendo determinista: prueba la orquestación y el tratamiento de una
omisión global, no la capacidad semántica de un proveedor real para detectarla.

**Dictamen de mitigación: pertinente para nueva validación, sin aprobación de
salidas nuevas.** La evaluación B de r12 sigue requiriendo cambios; la aprobación
histórica limitada de la evaluación A se conserva. Solo otra candidata exacta,
contrastada con sus fuentes, puede demostrar eficacia. No se modifican firmas,
estados humanos ni el veredicto del informe completo.
