---
phase: 2
builder: codex
reviewer:
verdict: pendiente
date: 2026-11-08
---

# Revisión de la fase 2: digest jerárquico y contraste científico

Esta ficha corresponde a D-047/D-048/D-049 e IN-07 a IN-12. La revisión anterior
se conserva en [phase-2-before-hierarchical.md](phase-2-before-hierarchical.md);
no aprueba este rediseño. Protocolo en [VALIDATION.md](../VALIDATION.md).

## Informe automático

[Puerta automática](../../build/gates/phase-2.md). La tarea IN-11 está en validación;
no se da por aprobada la fase. Última suite del constructor: 295 tests pasan,
con lint, formato y tipos. La auditoría preparatoria independiente está en
[review-hierarchical-precheck.md](../../build/review-hierarchical-precheck.md) y
[review-grounding-precheck.md](../../build/review-grounding-precheck.md).
La revisión de unidades está en
[review-unit-classifier-precheck.md](../../build/review-unit-classifier-precheck.md).

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
Las rutas concretas, las cinco afirmaciones cotejadas y la comparación móvil/vault
se adjuntarán al completar esta validación. No se infiere comprensión humana de
la validación automática ni del cotejo del constructor.

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
