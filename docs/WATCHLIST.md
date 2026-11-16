# Seguimiento solicitado por la persona

Propuesta WA-10, 2026-11-16. Pendiente de aprobación e implementación. Amplía
el cuaderno de WA-09 con preguntas y prioridades independientes de las tareas
de Kanvas. La aprobación técnica de fase 3 corresponde al código anterior;
esta ampliación requiere pruebas y una revisión adicional antes de cerrar WA-05.

## Entrada y edición

En la webapp, «Seguimiento» permite pegar una lista, revisar las fichas propuestas
y guardarlas mediante una acción explícita. También permite añadir una ficha
individual. Cada ficha contiene título, pregunta o criterio de seguimiento,
uno o varios proyectos o ámbito general, prioridad editable de 0 a 100
(50 inicial), fecha de creación y estado activo, pausado o archivado.
La prioridad ordena la atención; no aumenta automáticamente por antigüedad.

Se conserva el texto original y un historial de ediciones. Cambiar una pregunta
no reinterpreta los informes anteriores. Pausar o archivar conserva su historia;
ningún modelo cambia esos estados. El formulario rechaza ediciones obsoletas y
duplicaciones por reenvío. Crear una ficha no crea ni modifica tareas en Kanvas.

## Primeros ejemplos: benchmark

La persona ha pedido seguir estos tres temas. Las preguntas siguientes son
propuestas de concreción, no conclusiones ni criterios científicos aceptados:

| Tema aportado | Pregunta que orienta la revisión | Precaución al comparar |
| --- | --- | --- |
| Aumento de número de semillas por modelo | ¿Qué modelos tienen nuevas semillas y qué cobertura sigue pendiente? | Contar semillas únicas identificables; distinguir planificadas, iniciadas y terminadas. No equiparar archivos con semillas ni sumar intentos duplicados. |
| Resultados de dinámicas moleculares | ¿Qué resultados nuevos hay y qué permiten interpretar o revisar? | Distinguir trayectoria producida, análisis disponible y conclusión respaldada; indicar protocolo y comparabilidad cuando consten. |
| Cálculo de errores con cristales | ¿Qué errores se han calculado frente a estructuras cristalográficas y qué casos faltan? | Mostrar métrica, referencia y correspondencia estructural cuando estén documentadas; no asumir RMSD, alineamiento o significado de «error». |

El usuario podrá ajustar estas formulaciones antes de guardarlas. No se inventan
objetivos numéricos, métricas ni umbrales. Tampoco se presupone que un cálculo
está terminado por aparecer mencionado en una conversación.

## Qué significa monitorizar

Se cruzan los temas activos con evidencias de las fuentes ya configuradas y
permitidas, manteniendo sus límites de lectura. El modelo recibe preguntas y
evidencias acotadas, no permisos para elegir rutas ni ejecutar análisis.
Una ficha puede señalar fuentes que faltan; configurarlas requiere una acción
separada. Una ruta pegada como texto no amplía las raíces permitidas.

Cada evaluación identifica la revisión exacta de la ficha, intervalo, evidencias
consultadas y resultado: novedades respaldadas, sin novedades observadas,
evidencia insuficiente, fuente pendiente o fallo de cobertura. Ausencia de datos
no demuestra ausencia de trabajo. Solo se declara «sin novedades observadas»
si existe una base comparable y se ha comprobado la cobertura; en otro caso se
expresa la limitación. Una cifra o una interpretación exige evidencias y pasa
los validadores y el cotejo aplicables antes de publicarse.

La petición humana se identifica como tal: «prioridad alta» no es evidencia de
avance ni de importancia científica. Todos los resultados del intervalo siguen
apareciendo aunque no encajen en la lista. Las preferencias pueden orientar
el foco propuesto, sin sustituir misiones aceptadas ni cerrar revisiones humanas.

## Niveles del informe y formato propuesto

- Móvil/correo: hasta tres novedades o asuntos que requieren atención, ordenados
  por prioridad explícita y relevancia de la evidencia, con enlace al detalle.
  Se indica cuántos temas activos hay y cuántos quedan pendientes de evaluación.
- Web y vault: sección «Seguimiento solicitado» con todos los temas activos,
  su evaluación, evidencias, límites y siguiente comprobación sugerida. Los temas
  sin novedades o sin datos también aparecen. Historial por tema y por informe.
- Semanal: balance de las mismas preguntas, cambios comparables y revisión
  crítica de evidencias que contradigan o maticen conclusiones previas. Nuevos
  análisis se proponen; no se ejecutan ni se consideran aprobados.

Ejemplo de estructura Markdown; los corchetes son marcadores del diseño,
no una muestra de resultados reales:

```markdown
## Seguimiento solicitado

### Semillas por modelo · benchmark · prioridad 50
Pregunta: ¿Qué modelos tienen nuevas semillas y qué cobertura sigue pendiente?
Evaluación: [novedades / sin novedades observadas / evidencia insuficiente / …]
Evidencias: [IDs válidos y enlaces del informe]
Cambio comprobable: [comparación respaldada, o limitación explícita]
Pendiente de comprobar: [pregunta concreta, sin darla por resuelta]
```

Esta sección se añadiría a nuevas revisiones del diario y semanal en los
Markdown de Obsidian y las copias inmutables Markdown/JSON/PDF de Drive ya
previstas. No añade carpetas ni reescribe informes o notas humanos. El documento
estructurado identificaría ficha y revisión, evaluación y referencias; no
presentaría una pregunta humana como afirmación científica. Su contrato exacto
se documentará y probará durante WA-10. Se solicita aprobación de este cambio
de formato antes de implementarlo, conforme a AGENTS.md.

## Límites, privacidad y persistencia propuestas

Hasta treinta fichas activas; título de hasta 160 caracteres y pregunta de hasta
1000. El paquete de preguntas por generación tiene un máximo de 12 000 caracteres
y se construye antes de llamar al modelo, por prioridad y orden estable. Una
ficha que no cabe queda explícitamente pendiente en el detalle; no se recorta ni
se presenta como evaluada. Las evidencias mantienen además sus propios límites.

Las fichas se almacenarían con revisiones inmutables y huellas en `meta`, sin
cambiar el esquema SQLite publicado ni añadir dependencias. Cada trabajo fija
las revisiones utilizadas para que editar durante una generación no cambie su
entrada. Se hereda el ámbito histórico de privacidad de todos los proyectos
implicados; el ámbito general se resuelve explícitamente a proyectos permitidos,
sin convertirse en acceso global al disco. Retirar un proyecto o reducir el
ámbito visible no elimina restricciones heredadas. Si falta una política, no se
envía el contexto humano al proveedor. El respaldo sigue el de SQLite.

## Criterios de aceptación

Alta desde lista y ficha individual; edición, prioridades, pausa e historial;
las tres preguntas de benchmark guardadas solo tras confirmación del formulario.
Pruebas de seguimiento diario y semanal con evidencia nueva, duplicada,
incomparable y ausente; fuente no configurada; límites y cobertura incompleta;
edición concurrente y reanudación con revisiones fijadas; privacidad heredada,
inyección de instrucciones, HTML y proyectos intactos. Regresión de formatos y
entregas inmutables; `make check` y puerta automática de fase 3; revisión
independiente adicional y validación humana del detalle y resumen móvil.
