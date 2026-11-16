# Seguimiento solicitado por la persona

WA-10, aprobada por la persona en el tablero y el chat el 2026-11-16, incluido
el formato de la sección en Obsidian y Drive. Implementada; revisión técnica
adicional aprobada en `reviews/wa-10.md`; validación humana pendiente. Amplía
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

Esta sección se añade a nuevas revisiones del diario y semanal en los
Markdown de Obsidian y las copias inmutables Markdown/JSON/PDF de Drive ya
previstas. No añade carpetas ni reescribe informes o notas humanos. El documento
estructurado identifica ficha y revisión, evaluación y referencias; distingue
la pregunta humana de las afirmaciones científicas. La persona aprobó este
cambio de formato al aprobar WA-10; se mantienen los originales.

## Límites, privacidad y persistencia propuestas

Hasta treinta fichas activas; título de hasta 160 caracteres y pregunta de hasta
1000. El paquete de preguntas por generación tiene un máximo de 12 000 caracteres
y se construye antes de llamar al modelo, por prioridad y orden estable. Una
ficha que no cabe queda explícitamente pendiente en el detalle; no se recorta ni
se presenta como evaluada. Las evidencias mantienen además sus propios límites.

Las fichas se almacenan con revisiones inmutables y huellas en `meta`, sin
cambiar el esquema SQLite publicado ni añadir dependencias. Cada trabajo fija
las revisiones utilizadas para que editar durante una generación no cambie su
entrada. Se hereda el ámbito histórico de privacidad de todos los proyectos
implicados; el ámbito general se resuelve explícitamente a proyectos permitidos,
sin convertirse en acceso global al disco. Retirar un proyecto o reducir el
ámbito visible no elimina restricciones heredadas. Si falta una política, no se
envía el contexto humano al proveedor. El respaldo sigue el de SQLite.

## Contrato implementado

`/watchlist` permite pegar una lista o una sola pregunta; el POST
`/watchlist/preview` prepara la revisión previa sin guardar. Confirmar usa
`/watchlist/save`. `/watchlist/{id}` edita una ficha y pagina su historial.
La lista pagina treinta fichas y muestra el número total de activas. El historial
de la ficha enlaza hasta veinte informes recientes con ese tema. Se conserva
el texto humano original, sin normalizarlo mediante un modelo. Los secretos
conocidos se filtran antes de persistir o mostrar el contenido.

Cada ficha tiene ID `wl_…`. Sus revisiones usan el almacén inmutable `nb_revision`
y `nb_hash` con `kind: watchlist`, puntero `wl_item:<id>` y recibo idempotente
`wl_submission:<nonce>`. Un lote se guarda entero o se revierte entero; la huella
del catálogo detecta formularios obsoletos. No se añade migración SQLite.

El documento JSON del informe añade `watchlist`, con versión, lista de fichas
activas y huella. El inventario privado del trabajo lo fija antes de generar:
reanudar usa esas mismas preguntas aunque la persona haya editado la lista.
Los informes anteriores sin este campo siguen siendo legibles.

Cada evaluación validada vive en `sections["watch:<id>"]` y lleva paquete,
proveedor, modelo y prompt, más su cotejo `check:watch:<id>`. Usa la ruta
`conceptual`, configurable desde la pantalla de modelos. Incluye `status`,
`finding`, `meaning` con confianza, `limits`, `next_check` y `current_evidence`.
Los estados internos son `news`, `no_new`, `insufficient`, `source_pending` y
`coverage_failure`; la interfaz los traduce al español. La búsqueda de una base
anterior examina hasta tres informes completos del mismo tipo que terminen antes
del inicio del intervalo. Solo compara la misma revisión de la pregunta y hasta
64 evidencias históricas con 48 000 caracteres de extractos; no interpreta una
versión editada como la pregunta anterior. El semanal añade el modo crítico.

`no_new` exige una evaluación anterior respaldada (`news` o `no_new`) y cobertura
completa de todos los proyectos implicados. `news` exige citar en el hallazgo
alguna evidencia actual declarada. Ambos pasan además el validador común y el
cotejo de fidelidad; estas condiciones necesarias no demuestran validez científica.
El paquete de evaluación no recorta evidencias para caber: si excede su máximo
de 64 000 caracteres o el límite configurado, la generación queda pendiente.

Un tema omitido por el presupuesto global de preguntas o por política ausente,
o sin evidencias disponibles de sus proyectos, aparece explícitamente pendiente
de evaluación. Es un estado de disponibilidad calculado por el servicio, sin
conclusión científica mecánica. Si se intenta una evaluación y falla el modelo,
el validador o el cotejo, el informe queda pendiente y no se entrega.

El plan diario y la orientación semanal reciben las evaluaciones disponibles
como contexto humano, con sus preguntas y privacidad heredada. No reciben los
temas omitidos. Los enlaces de la ficha a informes se registran en
`wl_report:<informe>:<ficha>` y solo se muestran para informes completos.

## Criterios de aceptación

Alta desde lista y ficha individual; edición, prioridades, pausa e historial;
las tres preguntas de benchmark guardadas solo tras confirmación del formulario.
Pruebas de seguimiento diario y semanal con evidencia nueva, duplicada,
incomparable y ausente; fuente no configurada; límites y cobertura incompleta;
edición concurrente y reanudación con revisiones fijadas; privacidad heredada,
inyección de instrucciones, HTML y proyectos intactos. Regresión de formatos y
entregas inmutables; `make check` y puerta automática de fase 3; revisión
independiente adicional y validación humana del detalle y resumen móvil.
