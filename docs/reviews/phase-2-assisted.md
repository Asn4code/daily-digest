# Validación humana asistida, 2026-11-10

Registro de las respuestas de la persona durante la lectura guiada en conversación.
La muestra explicada fue `rep_in11_daily_levels_r17`; el semanal fue VCD11.
Este registro no marca las casillas de firma ni declara aceptación técnica,
comprensión de todos los resultados o aprobación global de la fase.

| Tema | Respuesta de la persona | Alcance registrado |
| --- | --- | --- |
| Carga del catión, alcance a un compuesto y misión propuesta | «me ayuda» | La explicación ayuda; no acepta las cargas ni compromete la misión. |
| Gráfica entre motores, frase original | «no, no me lo permite» | La frase sobre rankings no permite entender qué comparar. Necesita reformulación. |
| Gráfica, explicación de punto/ligando, ejes y poses distintas | «sí» | La reformulación resulta clara; debe incorporarse a la proyección del informe. |
| Selección para MD preparada, dinámica no ejecutada, decisión por motor pendiente | «sí» | La explicación permite distinguir esas situaciones; no acepta la decisión por motor. |
| Retención en prueba de humo frente a cobertura completa y resultado científico | «sí» | La explicación permite distinguir avance técnico de validación científica. |
| Precisión float16 y pLDDT por átomo/residuo | «vale la nota» | Conformidad con la explicación del límite; no aceptación de precisión ni granularidad. |
| Semanal VCD: interfaz nueva sin nueva medición; auditoría opcional de datos existentes | «ok» | Conformidad con el balance explicado; no ordena ejecutar la auditoría. |
| Ejecutabilidad de la misión sobre la carga | «que sabría empezar» | Confirma saber cómo empezar esa misión. No declara ejecución, finalización ni aceptación de resultados. |

## Aclaración de la gráfica

La explicación que recibió respuesta positiva identificó cada punto como un
ligando y cada eje como la puntuación de su mejor pose en el motor correspondiente.
Las dos poses pueden ser colocaciones distintas; comparar sus puntuaciones no
prueba que coincidan las estructuras. Se usó GNINA en X y AutoDock-GPU en Y como
ejemplo de configuración; la interfaz permite elegir los ejes. Al pulsar un punto
se abre la pose del motor seleccionado para X.

La primera revisión nueva (R21) conservó el detalle en la vault, pero no identificó
punto y ejes en el móvil. El revisor independiente la devolvió por claridad.
Project9 exige los tres elementos juntos en `reading_conditions`; las revisiones
previas se conservan. El cotejo y la ficha vigente deben identificar la revisión
final que realmente se presenta para firma.

Una misión distinta que el modelo proponga al regenerar no hereda la respuesta
«sabría empezar» de la misión sobre cargas. La elección del foco sigue siendo humana.

## Petición adicional

La persona pidió una opción al final del diario para solicitar más información
sobre sus frases, pedir comprobaciones y recibir un nuevo informe. Registrada en
D-050 y WA-08; [diseño](../ON_DEMAND_FOLLOWUPS.md) para la fase de webapp, todavía
no implementado. Esa petición tampoco constituye firma de fase 2.

Ante la elección entre ampliación y diario completo, la persona confirmó:
«Una ampliación centrada en las frases solicitadas». El original se conserva y
el seguimiento no vuelve a elegir su misión.

## Aprobación de fase

Tras la corrección de claridad, la revalidación independiente de R24 y la
solicitud explícita de aprobar la fase 2, la persona respondió «Apruebo».
La aprobación se transcribió con su procedencia en [phase-2.md](phase-2.md).
La puerta completa pasó a APROBADA; los estados de comprensión de resultados y
la aceptación de la misión en SQLite permanecen sin cambios.
