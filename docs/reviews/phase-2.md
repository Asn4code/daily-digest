---
phase: 2
builder: codex
reviewer: codex-independent
verdict: aprobada
date: 2026-11-10
---

# Revisión de la fase 2: digest jerárquico y contraste científico

Esta ficha corresponde a D-047/D-048/D-049 e IN-07 a IN-12. La revisión anterior
se conserva en [phase-2-before-hierarchical.md](phase-2-before-hierarchical.md);
no aprueba este rediseño. Protocolo en [VALIDATION.md](../VALIDATION.md).

**Estado actual de la puerta: APROBADA (2026-11-10).** Tras la aprobación expresa
de la persona, el constructor ejecutó `scripts/phase_gate.py 2` sin omitir revisión
ni firma: código 0, todos los controles PASS. Informe en
[build/gates/phase-2.md](../../build/gates/phase-2.md).
La firma y su procedencia están al final de esta ficha. Las menciones a firma
pendiente en los veredictos conservados describen el momento de esas revisiones,
anterior a esta aprobación humana; no son el estado actual de la puerta.

## Informe automático

**Revalidación formal final: aprobada técnicamente (2026-11-10).**
Revisor `codex-independent`, sesión `review_hierarchical_phase_two`, sobre
`8f3c8d82162d5a4a2de5a1a48c8570df0a64d81a` (Project9/Plan6). La puerta ejecutada
independientemente después de terminar la del constructor devuelve **PROVISIONAL,
exit3**, todos los controles automáticos PASS. El constructor registra la suite
completa de 319 pruebas PASS (60,21s); la puerta independiente vuelve a ejecutar
lint, formato, tipos, fixtures y escenarios exigidos. La revisión formal base ya
incluyó 319 pruebas completas ejecutadas por esta sesión el 9 de noviembre.

Muestra principal vigente: **diario 24**, con gráfico explicado en móvil/vault y
propuesta de cargas conservada explícitamente sin aceptación humana. No quedan
hallazgos importantes/bloqueantes abiertos para esta muestra y semanales VCD11/BM13.
[Revalidación final: cinco afirmaciones, misión, canales, paquetes y presupuesto](../../build/review-in11-main-r24.md).
La aprobación técnica no marca las comprobaciones ni firma de la persona.

### Historial de revalidación (conservado)

**Revalidación independiente de R22 (2026-11-10): cambios.** La puerta actual
sobre `e0f1ee2` devuelve PROVISIONAL (exit3), todo automático PASS. Project9 ya
conserva en móvil punto=ligando, valores de ejes y poses posiblemente distintas.
El foco nuevo, generado por DeepSeek, mezcla tolerancia de precisión de float16
con la decisión de trabajar sin PAE de ciertos modelos; esa tolerancia no resuelve
la cobertura incompleta. También omite el rango0-30 de la cota<0,01Å citada.
Hallazgo **importante** en `plan.mission.action/reason/done_criterion`, reproducible
en `rep_in11_daily_levels_r22/mobile.txt:16` y `report.md:211`. Test sugerido:
criterios separados para precisión y cobertura y conservación del rango de cota.
[Cotejo completo de cinco afirmaciones, canales, metadatos y misión](../../build/review-in11-main-r22.md).
No se aplica a este foco la respuesta humana sobre la misión de cargas de R17.
La aprobación técnica del 9 de noviembre se conserva debajo como histórica;
la versión nueva queda pendiente de corrección y cotejo, sin firmas humanas.

**Revalidación de claridad en curso (2026-11-10).** La persona indicó que la frase
sobre comparabilidad de poses no le permitía interpretar la gráfica. Confirmó
que la explicación de punto/ligando, ejes por motor y posibles poses distintas
sí resultaba clara. Project9 exige esa unidad y los ejes juntos en las condiciones
visibles del móvil, manteniendo el paquete acotado; se prepara una revisión
nueva del diario. La aprobación técnica del 9 de noviembre conservada debajo
corresponde a las versiones anteriores y no sustituye esta revalidación ni la
firma humana. D-050/WA-08 recoge además la ampliación a petición para fase 3,
todavía no implementada.

[Puerta automática](../../build/gates/phase-2.md). Las muestras de IN-11 están
completas y cotejadas; no se da por aprobada la fase. Revisión formal independiente sobre `07a3940` (producción `59647de`):
319 tests pasan en 56,01 s, con lint, formato y tipos ejecutados por el revisor.
La puerta ejecutada por esta sesión devuelve PROVISIONAL (exit 3), todo automático
PASS; revisión y firma se omiten únicamente por `--no-manual`.
El detalle reproducible, mapa completo de FR y pruebas está en
[review-phase-two-formal.md](../../build/review-phase-two-formal.md). La auditoría preparatoria independiente está en
[review-hierarchical-precheck.md](../../build/review-hierarchical-precheck.md) y
[review-grounding-precheck.md](../../build/review-grounding-precheck.md).
La revisión de unidades está en
[review-unit-classifier-precheck.md](../../build/review-unit-classifier-precheck.md).
El cotejo de reparación acotada está en
[review-repair-diagnostics-precheck.md](../../build/review-repair-diagnostics-precheck.md)
y los contrastes semanales, incluidos rechazos y falsos positivos del modelo, en
[review-weekly-vcd-critical-precheck.md](../../build/review-weekly-vcd-critical-precheck.md).

## Hallazgos y revalidación independiente

Revisor `codex-independent`, sesión `review_hierarchical_phase_two`, 2026-11-09.
Sesión distinta de la construcción; no ha modificado producción, proyectos,
Kanvas ni estados humanos. Leídos los documentos exigidos por VALIDATION §4.

- **Importante, corregido y revalidado:** los IDs de pruebas no correspondían a
  TESTING: T13 estaba asignado a unidades y T17 a delimitación de instrucciones;
  la reparación JSON quedaba fuera de la selección T17. Repro inicial:
  `pytest --collect-only -q -k T17`. Corrección `07a3940` en
  `tests/unit/test_llm_validation.py:57`, `:183`, `tests/unit/test_llm_router.py:346`
  y `tests/e2e/test_llm_report.py:26`: T12 cubre cifras/unidades, T13 inyección,
  T17 reparación JSON y publicación local completa. La selección T12/T13/T17
  ejecuta siete pruebas correctas; la puerta repetida es PROVISIONAL.
- **Menor, opcional:** `src/digest/report/render_md.py:16` escapa el `#` de la
  entidad creada para un apóstrofo: `escape("'14/14 conf guardados'")` produce
  `&\#x27;14/14 conf guardados&\#x27;`, que MarkdownIt muestra como texto de
  entidades. Se observa en el Markdown de Benchmark13. Afecta legibilidad;
  no altera citas, cifras, unidades o seguridad, ni el HTML/correo directo.
  Test sugerido: texto visible de una afirmación con apóstrofos tras renderizar
  Markdown, conservando el rechazo/escapado de HTML malicioso. Seguimiento
  propuesto por el constructor: WA-07 (dependiente de IN-06), sin aprobar ni
  implementar esa tarea futura.

No quedan hallazgos bloqueantes o importantes abiertos. H1–H4 (ámbito humano,
fechas/localizador, versiones sustituidas y privacidad ancestral) y G1 (certificado
sin fuentes/contexto exactos) están corregidos y revalidados por pruebas y ataques
nuevos. S1/S3/S10 están cerrados en el diario17 final; S7/S8/S9 y atribución están
cerrados en Benchmark13 final. VCD11 conserva decisiones humanas, alcance y
contraste sin cambio material sin fabricar una alerta nueva. Los rechazos y
aprobaciones automáticas equivocadas se conservan en los prechecks enlazados:
un cotejo de modelo no demuestra verdad científica ni comprensión humana.

### Cierre de la revalidación de claridad y foco (2026-11-10)

- **Importante, corregido en R24:** R21 dejaba punto/ejes solo en la vault.
  Project9 los conserva juntos en la condición móvil: punto=ligando,
  eje=puntuación de mejor pose en su motor, poses posiblemente distintas y
  puntuaciones no prueban coincidencia estructural. [Cotejo R21](../../build/review-in11-main-r21.md).
- **Importantes, corregidos en R24:** el focoR22 mezclaba precisión con cobertura
  y omitía el rango de la cota; R23 usaba RMSD como control de trazabilidad y
  selección mezclada no definida. Se conservan [R22](../../build/review-in11-main-r22.md)
  y [R23](../../build/review-in11-main-r23.md) como intentos devueltos, no aprobados
  retroactivamente. Plan6 distingue controles/decisiones y el modo editorial
  genera la propuesta de cargas R17 exacta, con control y criterio previos propios.
- **Retención editorial acotada:** el driver privado suministra propuesta y
  report_id/cache_key originales, `accepted_by_human=False`, scope anterior⊆actual
  y mensajes de25.067 caracteres (tope32.000), con Router/validación/cotejo normales.
  El paquete y certificado conservan ese contexto; no se monta como texto humano
  ni como plan aceptado. No acredita una función nueva de retención en producción.

R17/R22/R24 revalidados; las secciones/paquetes ajenos al plan son idénticos aR22 y el
plan final es idéntico aR17. Cuatro manipulaciones nuevas de binding rechazadas,
correo completo igual a sus vistas TXT/HTML; dos resultados pending. No se
repiten40 ataques de base sin cambios que lo requieran. Sigue solo el menor WA-07.
La [revisión asistida](phase-2-assisted.md) contiene respuestas con alcance propio;
no es firma global ni aceptación/ejecución del informe nuevo. D-050/WA-08 permanece
solo diseño futuro de un suplemento sobre frases seleccionadas, sin reescribir
el diario original ni implementar la funcionalidad durante esta fase.

### Requisitos, implementación y pruebas

| Requisitos de fase 2 y regresión | Código | Verificación |
| --- | --- | --- |
| FR-02/03/04, nuevas fuentes sin ejecución | `collectors/notebooks.py`, `structures.py`, `agent_sessions.py`, `results.py` | `test_phase_two_collectors`, T11/T30, hashes de árboles incluidos `.git` |
| FR-10–15/19, ventanas, plazos, fallos y reanudación | `worker.py`, `intervals.py`, `builder.py`, `completeness.py`, `loading.py` | T16/T18, `test_resumable_generation`, fallos parciales y entrega incompleta rechazada |
| FR-16/17 y D-049, interpretación/inventario/foco | `report/activity.py`, `daily.py`, `assembly.py`, `context.py`, `validator.py` | T01/T02, `test_daily_levels`, plan humano preservado y tareas por proyecto |
| FR-18, crítica versionada desde evidencias | `report/conclusions.py`, `weekly.py`, `schemas.py`, `validator.py` | `test_weekly_critical`, `test_weekly_baselines`, ambas líneas de evidencia, texto/estado humano intactos |
| FR-20–24, móvil/vault y entrega | `views.py`, renders/plantillas, `publish/email.py` | condiciones sin destacados, texto/HTML, quiet semanal, cinco afirmaciones y tres muestras finales |
| NFR-02/04, identidad/caché/linaje | `llm/cache.py`, `router.py`, `grounding.py`, `contracts.py` | `test_node_cache`, ramas independientes, auditar de nuevo solo la capa cambiada |
| Privacidad, secretos y publicación obligatoriamente validada | `context.human_scope`, `conclusions.py`, `util/redact.py`, `validator.py`, `deliveries.py` | política ausente bloquea texto humano, privado solo internal, secretos fuera de nodos/wire, T12/T13/T15/T17 |

Mapa ampliado y referencias a nombres de prueba en el
[informe formal](../../build/review-phase-two-formal.md).

### Intentos deliberados

Se ejecutó FakeLLM con ID/cifra inventados y cifra correcta con otra unidad;
se revisó delimitación de instrucciones maliciosas y ausencia de herramientas
o acciones controladas por el modelo. La caída de proveedor conserva el modelo
real efectivo; un ámbito privado no llama a NaN. La caída total deja borrador
sin entrega/cierre y la recuperación revalida antes de publicar.

Además de la suite, **40 alteraciones rechazadas** sobre tres informes finales y
contratos numéricos: cambiar fechas/localizador/calidad temporal, quitar o alterar
certificado, candidato, contexto o fuentes, y ocultar unidades/denominadores tras
clasificadores. Registro en
[review-phase-two-formal-adversarial.json](../../build/review-phase-two-formal-adversarial.json).
Un recorrido nuevo sobre fixtures usa solo MockTransport, conserva hashes de los
tres árboles incluidos `.git`, no crea entregas ni planes aceptados. Cinco
afirmaciones seleccionadas con semilla fija se cotejaron con sus evidencias; son
frases genéricas del doble, no una prueba de calidad científica de modelos.
La semántica científica se cotejó independientemente en las muestras reales.

## Muestras reales y límites

Están en `build/in11-validation/`, con notas originales de los dos
proyectos y fechas originales. Son muestras retrospectivas y de cobertura parcial;
no verifican ejecuciones ni representan toda la producción de los proyectos.
No se envía correo, no se copia a Drive y no se escriben proyectos observados.

La muestra previa de IN-10 se conserva en `build/in10-sample/sample-r3/`.
El diario vigente cotejado es `rep_in11_daily_levels_r24`, con
[móvil](../../build/in11-validation/data/reports/rep_in11_daily_levels_r24/mobile.html)
y [vault](../../build/in11-validation/data/reports/rep_in11_daily_levels_r24/report.html).
Las cinco afirmaciones, condiciones y foco se cotejan en
[review-in11-main-r24.md](../../build/review-in11-main-r24.md).
La muestraR17 conserva su [cotejo histórico](../../build/review-in11-main-r17.md)
y [source-checks.md](../../build/in11-validation/source-checks.md); la misión de
cargas permanece propuesta automática sin aceptación/ejecución. La revalidación
no se aplica a los focos distintos de R21/R22/R23 que se devolvieron.
El semanal de VCD cotejado es
[`rep_in11_weekly_vcd_r11`](../../build/in11-validation/data/reports/rep_in11_weekly_vcd_r11/report.html).
El semanal de Benchmark cotejado es
[`rep_in11_weekly_benchmark_r13`](../../build/in11-validation/data/reports/rep_in11_weekly_benchmark_r13/report.html).
El revisor detectó y volvió a comprobar las correcciones de atribución temporal y
criterio de utilidad científica, incluso ante cotejos de modelo positivos.
El registro, incluidos rechazos y cierre de la muestra final, se conserva en
[review-weekly-benchmark-critical-precheck.md](../../build/review-weekly-benchmark-critical-precheck.md).

En estas muestras privadas se usaron modelos de NaN: extracción Mimo-v2.6-flash
para Benchmark y GLM5.3-flash para VCD; balances, orientación y plan del diario con
DeepSeek-v4-flash. La crítica semanal de VCD usa GLM5.3-flash y su agregado y
cotejos DeepSeek-v4-flash. En Benchmark, crítica y agregado usan DeepSeek-v4-flash
y sus cotejos GLM5.3-flash; la crítica declara el suplemento de auditoría 6.1.
Cada `report.json` conserva el modelo efectivo y qué
piezas se reutilizaron. La configuración de producción no cambia por este ensayo.
No se infiere comprensión humana de la validación automática ni de estos cotejos.
La [verificación final privada de R24](../../build/in11-validation/final-validation-r24.json)
identifica evidencias, estados pendientes, modelos, prompts y seis hashes de
archivos, comprobados independientemente. El
[manifiesto original del 9 de noviembre](../../build/in11-validation/final-validation.json)
se conserva intacto como histórico de diario17 y semanales vigentes.

## Excepciones «gate: allow» revisadas

No existen excepciones en `src/` ni plantillas. Las dos anotaciones de
`scripts/phase_gate.py:155` y `:212` justifican subprocess del script de puerta
(comandos fijos de comprobación y pytest), fuera del código del servicio. Usan
listas y timeout, sin shell ni ejecución de contenido recogido de proyectos.
No exceptúan publicación, privacidad, secretos o HTML. Revisión aceptada.

## Veredicto del revisor

**Aprobada técnicamente**, revalidada el 2026-11-10 por `codex-independent`, sesión
`review_hierarchical_phase_two`, sobre `8f3c8d8` y diario 24. Puerta independiente
PROVISIONAL, todo automático PASS; cotejo final sin defectos materiales abiertos.
El menor WA-07 de presentación continúa opcional. Project9 corrige claridad y
Plan6 mantiene foco validado como propuesta automática explícita, sin aceptación.

Esta es la aprobación de la capa independiente de VALIDATION §4. Quedan
exclusivamente las comprobaciones y firma humanas de la ficha, sin marcar por el
revisor. No se declara comprensión global, orden de ejecutar la misión ni
aprobación de fase completa. Muestras retrospectivas, parciales y agrupadas de
forma curada: no demuestran captura completa o asociaciones científicas naturales
entre tareas distintas; el modo editorial privado tampoco implementa WA-08.

### Aprobación técnica histórica del 9 de noviembre

**Aprobada técnicamente** por `codex-independent` (sesión
`review_hierarchical_phase_two`) el 2026-11-09, sobre `07a3940` y producción
`59647de`. Puerta independiente PROVISIONAL, calidad y 319 pruebas pasan,
intentos adversariales y cotejo final documentados. Hallazgo importante de
selección de escenarios corregido; queda un menor opcional de presentación.

Esta aprobación corresponde a la capa independiente de VALIDATION §4. La fase
sigue pendiente de las comprobaciones y firma de la persona: no se declara
comprensión, utilidad humana aprobada ni autorización de entrega por esta ficha.
Las muestras son retrospectivas y curadas; no validan captura completa ni
asociaciones científicas automáticas entre tareas distintas.

## Firma de la persona

Solo la persona marca estas casillas:

Registro de la aprobación expresa en conversación: 2026-11-10, 13:21:55 UTC.
«Apruebo», en respuesta a la solicitud de aprobar la fase 2 tras la lectura
asistida y la revalidación de R24. Codex transcribe esa aprobación en esta ficha;
no marca resultados como comprendidos ni acepta la misión en la base de datos.

- [x] En una muestra de 5 afirmaciones de un informe real, todas se sostienen al abrir sus evidencias
- [x] El plan de mañana es ejecutable: cada tarea tiene acción y criterio de finalización claros
- [x] El informe semanal de prueba aporta algo que no estaba en los diarios

Al comprobarlas, revisa también que móvil y vault conservan condiciones y límites,
que se distingue historia de actividad nueva y que la crítica permite entender
por qué una interpretación se mantiene o cambia. La elección del foco y el estado
de comprensión siguen siendo tuyos.

- [x] Apruebo la fase


Las notas de distintas tareas se agrupan de forma curada en una unidad de
validación por proyecto (`res_in11_vcd` / `res_in11_benchmark`). Sus IDs, fechas
y localizadores de evidencia son originales; estas agrupaciones no son resultados
creados por el agrupador de producción. El ensayo valida explicación, referencias,
foco y contraste después de esa agrupación. No acredita que el servicio descubra
automáticamente una relación científica entre tareas distintas ni representa todos
los resultados de los proyectos. La crítica actual busca evidencia posterior del
mismo resultado; ampliar esa relación necesita política explícita y evaluación
con datos del piloto, sin asociar tareas solo por parecido textual.
