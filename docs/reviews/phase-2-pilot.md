# Comprobaciones humanas del digest jerárquico

La ficha vigente es [phase-2.md](phase-2.md). La prueba anterior se conserva en
[phase-2-pilot-before-hierarchical.md](phase-2-pilot-before-hierarchical.md);
no debe usarse para aprobar el rediseño.

Las muestras se preparan en [build/in11-validation](../../build/in11-validation/).
El [índice privado](../../build/in11-validation/README.md) identifica las revisiones
completas y sus vistas. No firmes una revisión anterior ni un borrador pendiente.
La comprobación técnica no marca las casillas humanas.

El diario que ha superado el cotejo independiente es
[`rep_in11_daily_levels_r17`: móvil](../../build/in11-validation/data/reports/rep_in11_daily_levels_r17/mobile.html)
y [vista extensa](../../build/in11-validation/data/reports/rep_in11_daily_levels_r17/report.html).
El semanal de VCD cotejado es
[`rep_in11_weekly_vcd_r11`](../../build/in11-validation/data/reports/rep_in11_weekly_vcd_r11/report.html).
Benchmark sigue pendiente de resolver el cotejo semanal; estas dos muestras no
constituyen por sí solas la aprobación de la fase.

En el diario, comprueba que la carga 0 frente a la formal +1 solo afecta al ligando
ZINC000027515227; que la comparación del scatter es por ligando y mejor pose de
cada motor; y que simular ambos motores requeriría dos lanzamientos en total,
uno por motor. La misión propone fijar primero el criterio de carga y después
contrastar preparaciones del mismo compuesto. Sigue siendo una propuesta para ti.

En el semanal de VCD, «sin cambio material» conserva el alcance moderado de la
conclusión anterior. La interfaz y la selección de poses no aportan una nueva
medición del acuerdo ni una dinámica ejecutada. La auditoría de archivos propuesta
es opcional y distingue reproducción, discrepancia y resultado no evaluable.

Son muestras retrospectivas acotadas de notas reales de Benchmark y VCD. Conservan
sus fechas y distinguen declaraciones de agentes de resultados verificados.
No representan toda la actividad actual y no han enviado correo ni escrito en
los proyectos, la vault o Drive. El archivo mobile.html permite comparar el texto
del correo con report.html, que representa la vista extensa de la vault.

1. Abre el diario completo y elige cinco afirmaciones. Busca sus IDs en el bloque
   de evidencias del mismo informe y comprueba texto, cifras, unidades, controles
   y fecha. Una pregunta también puede presuponer un hecho falso. Si solo hay una
   declaración de agente, la afirmación debe conservar ese alcance.
2. Compara mobile.html y report.html: mismo significado y límites decisivos; la
   vista extensa debe ayudarte a profundizar sin obligarte a leerlo todo en el
   móvil. Comprueba especialmente las condiciones que cambian la comparación.
3. Revisa la misión: ¿resuelve una incertidumbre o desbloquea una decisión real
   del proyecto? ¿Sabes qué hacer y cuándo darla por terminada? Puedes rechazarla
   o proponer otro foco; una propuesta del modelo no es un compromiso aceptado.
4. Abre los semanales y busca una conclusión previa, evidencia posterior y el
   motivo de mantenerla, matizarla o cuestionarla. Distingue explicación histórica
   de descubrimiento nuevo. Si propone un análisis, comprueba alternativas,
   control, predicciones y criterio de decisión. No se ha ejecutado ese análisis.

Marca solo las comprobaciones satisfactorias y «Apruebo la fase» en
[phase-2.md](phase-2.md). Si algo falla, indica la revisión, el texto y su evidencia;
se genera otra revisión sin sobrescribir tus respuestas. La fase siguiente espera
la puerta aprobada. Un cotejo automático positivo puede equivocarse y no sustituye
esta lectura ni tu comprensión.


Las notas de distintas tareas se agrupan de forma curada en una unidad de
validación por proyecto (`res_in11_vcd` / `res_in11_benchmark`). Sus IDs, fechas
y localizadores de evidencia son originales; estas agrupaciones no son resultados
creados por el agrupador de producción. El ensayo valida explicación, referencias,
foco y contraste después de esa agrupación. No acredita que el servicio descubra
automáticamente una relación científica entre tareas distintas ni representa todos
los resultados de los proyectos. La crítica actual busca evidencia posterior del
mismo resultado; ampliar esa relación necesita política explícita y evaluación
con datos del piloto, sin asociar tareas solo por parecido textual.
