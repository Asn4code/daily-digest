---
phase: 2
builder: codex
reviewer:
verdict: pendiente
date: 2026-11-09
---

# Revisión de la fase 2: digest jerárquico y contraste científico

Esta ficha corresponde a D-047/D-048/D-049 e IN-07 a IN-12. La revisión anterior
se conserva en [phase-2-before-hierarchical.md](phase-2-before-hierarchical.md);
no aprueba este rediseño. Protocolo en [VALIDATION.md](../VALIDATION.md).

## Informe automático

[Puerta automática](../../build/gates/phase-2.md). La tarea IN-11 está en validación;
no se da por aprobada la fase. Última suite del constructor: 317 tests pasan,
con lint, formato y tipos. La auditoría preparatoria independiente está en
[review-hierarchical-precheck.md](../../build/review-hierarchical-precheck.md) y
[review-grounding-precheck.md](../../build/review-grounding-precheck.md).
La revisión de unidades está en
[review-unit-classifier-precheck.md](../../build/review-unit-classifier-precheck.md).
El cotejo de reparación acotada está en
[review-repair-diagnostics-precheck.md](../../build/review-repair-diagnostics-precheck.md)
y los contrastes semanales, incluidos rechazos y falsos positivos del modelo, en
[review-weekly-vcd-critical-precheck.md](../../build/review-weekly-vcd-critical-precheck.md).

## Hallazgos y revalidación independiente

Pendiente de la pasada formal del revisor. La auditoría preparatoria detectó
ámbitos humanos incompletos, procedencia temporal alterable, recuperación de
versiones sustituidas y pérdida de privacidad ancestral. Se han incorporado
correcciones y regresiones; el revisor debe registrar su verificación final.

## Muestras reales y límites

Se están preparando en `build/in11-validation/`, con notas originales de los dos
proyectos y fechas originales. Son muestras retrospectivas y de cobertura parcial;
no verifican ejecuciones ni representan toda la producción de los proyectos.
No se envía correo, no se copia a Drive y no se escriben proyectos observados.

La muestra previa de IN-10 se conserva en `build/in10-sample/sample-r3/`.
El diario cotejado es `rep_in11_daily_levels_r17`, con
[móvil](../../build/in11-validation/data/reports/rep_in11_daily_levels_r17/mobile.html)
y [vault](../../build/in11-validation/data/reports/rep_in11_daily_levels_r17/report.html).
Sus cinco afirmaciones y campos se identifican en
[source-checks.md](../../build/in11-validation/source-checks.md), con cotejo
[independiente del diario](../../build/review-in11-main-r17.md).
El semanal de VCD cotejado es
[`rep_in11_weekly_vcd_r11`](../../build/in11-validation/data/reports/rep_in11_weekly_vcd_r11/report.html).
El de Benchmark sigue pendiente: el revisor detectó atribuciones temporales y un
criterio de utilidad científica incorrectos incluso con un cotejo de modelo positivo.
El registro se conserva en
[review-weekly-benchmark-critical-precheck.md](../../build/review-weekly-benchmark-critical-precheck.md).

En estas muestras privadas se usaron modelos de NaN: extracción Mimo-v2.6-flash
para Benchmark y GLM5.3-flash para VCD; balances, orientación y plan del diario con
DeepSeek-v4-flash. La crítica semanal de VCD usa GLM5.3-flash y su agregado y
cotejos DeepSeek-v4-flash. Cada `report.json` conserva el modelo efectivo y qué
piezas se reutilizaron. La configuración de producción no cambia por este ensayo.
No se infiere comprensión humana de la validación automática ni de estos cotejos.

## Excepciones «gate: allow» revisadas

Pendiente de revisión independiente.

## Veredicto del revisor

Pendiente. La auditoría preparatoria no sustituye el protocolo formal de la puerta.

## Firma de la persona

Solo la persona marca estas casillas:

- [ ] En una muestra de 5 afirmaciones de un informe real, todas se sostienen al abrir sus evidencias
- [ ] El plan de mañana es ejecutable: cada tarea tiene acción y criterio de finalización claros
- [ ] El informe semanal de prueba aporta algo que no estaba en los diarios

Al comprobarlas, revisa también que móvil y vault conservan condiciones y límites,
que se distingue historia de actividad nueva y que la crítica permite entender
por qué una interpretación se mantiene o cambia. La elección del foco y el estado
de comprensión siguen siendo tuyos.

- [ ] Apruebo la fase


Las notas de distintas tareas se agrupan de forma curada en una unidad de
validación por proyecto (`res_in11_vcd` / `res_in11_benchmark`). Sus IDs, fechas
y localizadores de evidencia son originales; estas agrupaciones no son resultados
creados por el agrupador de producción. El ensayo valida explicación, referencias,
foco y contraste después de esa agrupación. No acredita que el servicio descubra
automáticamente una relación científica entre tareas distintas ni representa todos
los resultados de los proyectos. La crítica actual busca evidencia posterior del
mismo resultado; ampliar esa relación necesita política explícita y evaluación
con datos del piloto, sin asociar tareas solo por parecido textual.
