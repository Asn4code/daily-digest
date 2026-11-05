# Especificación funcional

Estado: v1, 4 de noviembre de 2026. Usuario único: un investigador postdoctoral en bioinformática estructural que trabaja con agentes de código y planifica en Kanvas.

## 1. Problema

La persona produce mucho trabajo (propio y de agentes) pero no tiene tiempo de revisarlo ni entenderlo. Necesita: saber qué se ha hecho, decidir qué hacer mañana y dedicar unos minutos a comprender de verdad algún resultado, sin abrir el tablero ni el IDE por la noche.

## 2. Glosario

| Término | Definición |
| --- | --- |
| Proyecto | Directorio raíz configurado, con su `kanvas.json`, objetivo y reglas de lectura |
| Captura (snapshot) | Lectura de una fuente en un instante, con hash |
| Evidencia | Hecho verificable con fuente, localizador, hash, hora y extracto acotado (ver `EVIDENCE.md`) |
| Resultado | Grupo de evidencias que forman una unidad de trabajo, normalmente una tarea de Kanvas con sus commits, figuras y ejecuciones |
| Intervalo | Periodo que cubre un informe: diario, semanal o avance |
| Informe | Documento generado para un intervalo, con revisión (`r1`, `r2`…) |
| Revisión | Explicación humana de un resultado, su contraste y la decisión humana |
| Entrega | Envío de un informe o revisión a un canal: correo, Obsidian o Drive |
| Trabajo (job) | Petición encolada: informe diario, semanal, avance, captura, entrega, copia |

## 3. Requisitos funcionales

### Captura

- **FR-01** El sistema captura periódicamente (por defecto cada 2 h) y al generar cada informe las fuentes de cada proyecto definidas en `EVIDENCE.md`.
- **FR-02** La captura es de solo lectura y respeta rutas permitidas, exclusiones y límites de tamaño. Lo omitido se registra como cobertura incompleta.
- **FR-03** Las evidencias se deduplican por `(proyecto, fuente, localizador, hash)`. Un cambio conocido aparece una sola vez en un informe.
- **FR-04** Las evidencias se agrupan en resultados. Una tarea de Kanvas que pasa a `review` o `done` genera o actualiza un resultado.

### Informes

- **FR-10** Informe diario: cubre desde el cierre del último diario hasta el disparo.
- **FR-11** Disparo automático diario a la hora configurada (por defecto 20:00 `Europe/Madrid`). Si ya hay un diario lanzado a mano ese día y no hay actividad nueva, el automático no genera nada.
- **FR-12** Disparo manual: botón en la webapp y `digest run` en la terminal.
- **FR-13** Avance (`--preview`): genera el informe sin cerrar el intervalo ni entregar.
- **FR-14** Informe semanal: el sábado (por defecto 10:00) cubre los 7 días anteriores, de sábado a viernes. También manual con `digest run --weekly`.
- **FR-15** No hay prisa: la generación puede tardar hasta `schedule.max_generation_minutes` (60 por defecto). El correo sale al terminar con las secciones requeridas validadas; agotar el plazo no autoriza publicar un respaldo mecánico.
- **FR-16** Contenido del informe diario completo, en este orden:
  1. Lo esencial: hasta 3 hechos con evidencias.
  2. Balance conceptual por proyecto: qué se sabe ahora, qué sigue sin saberse, qué decisión cambia. Se admite «hoy no hay conclusión científica nueva».
  3. Todo lo hecho: **todos** los resultados del intervalo, sin límite, cada uno con resumen, evidencias, figuras y estado de revisión.
  4. Plan de mañana: 1 misión y hasta 2 calentamientos (menos de 15 min), cada uno con acción, criterio de finalización, dependencia, motivo de prioridad y origen (`kanvas`, `model`, `review`). El motivo conecta la propuesta con el objetivo científico, una decisión o bloqueo que resuelve, las dudas/controles pendientes y los compromisos humanos. La persona conserva la elección y las ediciones; no se proponen tareas por rellenar el plan (D-049).
  5. Hilos abiertos: cambios sin confirmar, tareas en `doing`, preguntas `ask` sin responder.
  6. Nivel técnico: análisis ejecutados, parámetros determinantes, controles, fallos y bloqueos.
  7. Evidencias y cobertura: fuentes, intervalos no cubiertos, errores del servicio.
- **FR-17** Sin actividad verificable, el informe lo dice sin inferir que no se trabajó.
- **FR-18** Contenido del semanal: avance de cada proyecto frente a su objetivo; todas las tareas de la semana por proyecto y tema; revisiones hechas, pendientes por antigüedad y dudas; patrones (bloqueos repetidos, tareas que reaparecen, trabajo fuera del tablero); 4 a 6 figuras clave; propuesta de 2 o 3 objetivos y una sesión de revisión para la semana siguiente. Se construye desde las evidencias, no desde los diarios. Incluye una etapa crítica que contrasta conclusiones previas con evidencia nueva: qué se refuerza, matiza, pone en duda o queda sin resolver, y qué análisis concreto ayudaría a discriminar explicaciones. Conserva alcance, controles, incertidumbre y referencias históricas; no modifica automáticamente la revisión humana (D-048).
- **FR-19** Si fallan los proveedores o una sección no supera la validación, la generación queda pendiente y conserva sus avances válidos; no se sustituye esa sección por contenido mecánico ni se entrega un informe final incompleto. Todos los resultados y los motivos pendientes deben permanecer visibles en el inventario de trabajo. El informe final exige todas las secciones requeridas validadas (D-047; implementación propuesta en `HIERARCHICAL_DIGEST.md`).

- **FR-24** Profundidad por canal: el mensaje móvil conserva lo esencial, su significado y las limitaciones decisivas; la vault desarrolla niveles de orientación, comprensión conceptual y comprobación técnica desde el mismo contenido validado. El diario ofrece interpretación con profundidad intermedia; el semanal añade el contraste crítico. El contexto histórico del arranque se distingue de actividad nueva, sin ocultar los resultados del intervalo (D-048).

### Correo

- **FR-20** Correo diario esencial (lectura de 1 minuto): botón al informe en la webapp; lo esencial; **todas** las tareas hechas, una línea cada una (ID, título, proyecto), agrupadas por proyecto; plan de mañana; resultado propuesto para revisar con su figura; avisos en una línea; enlace «Abrir en Drive».
- **FR-21** HTML y texto plano, 1 o 2 figuras incrustadas (CID), sin fondo oscuro forzado, legible en móvil.
- **FR-22** `Message-ID` estable por informe y revisión. Estado incierto no se reenvía solo.
- **FR-23** El semanal se envía con el mismo formato, ampliado.

### Webapp

- **FR-30** Webapp adaptable a móvil y ordenador, instalable como PWA, accesible desde el enlace del correo (ver `WEBAPP.md`).
- **FR-31** Pantallas: Hoy, detalle de resultado, Revisar, Plan, Semana, Historial, Generar.
- **FR-32** Revisión: se propone un resultado al día; la persona puede revisar cualquiera, sin límite. La explicación del modelo queda oculta hasta enviar la propia. Modos completo, breve y mínimo. Contraste en cuatro listas: respaldado, omisión relevante, afirmación no respaldada, no verificable; más errores detectados en el resumen automático.
- **FR-33** Decisión humana: cerrar, requiere aclaración o posponer. Las dudas pasan como propuestas al plan siguiente.
- **FR-34** Una revisión abierta no genera fichas nuevas encima; la webapp vuelve a ofrecerla o deja elegir otra.
- **FR-35** Los botones de generar encolan trabajos; nunca ejecutan nada en el proceso web.

### Obsidian

- **FR-40** Escribe `Digest/AAAA-MM-DD.md`, `Digest/Semanal/AAAA-Wss.md` y `Revisiones/AAAA-MM-DD-<result_id>.md`. Escritura atómica. Nunca modifica otras notas.
- **FR-41** Si la webapp no está disponible, la ficha de revisión admite la respuesta humana; se procesa solo cuando su front matter dice `estado: lista`.

### Google Drive

- **FR-50** Copia remota continua en la carpeta configurada: informes (Markdown y PDF), figuras, fichas de revisión, plan aceptado, `indice.md` y copia diaria de SQLite (se conservan 30 días).
- **FR-51** Sube tras cada informe, cada revisión cerrada y cada copia nocturna. Incremental. Sin red, queda pendiente.
- **FR-52** Nunca sobrescribe ni borra fuera de `backups/`.
- **FR-53** Con la copia de Drive se puede restaurar el sistema (`digest restore`).

### Kanvas

- **FR-60** Lee `kanvas.json` de cada proyecto tras `kanvas check`. Si `kanvas` (versión de esquema) no es 1, omite la fuente y avisa.
- **FR-61** Usa las notas fechadas como hora de evento; distingue `done` (aceptado) de comprendido.
- **FR-62** (Fase 5, opcional) Propone tareas de interpretación o dudas con `kanvas propose --as digest`. Nunca aprueba, mueve ni edita.

### Extensiones (fase 6, ver `EXTENSIONS.md`)

- **FR-70** El núcleo no genera contenido docente, protocolos ni textos de métodos. Los hace posible con oportunidades y briefs para herramientas externas.
- **FR-71** Las extensiones se registran sin tocar el núcleo (internas en `src/digest/extensions/` o externas por el punto de entrada `daily_digest.extensions`) y cumplen el contrato de `EXTENSIONS.md` §4.
- **FR-72** Las oportunidades se proponen en el informe semanal (máximo 3) y en la pantalla Oportunidades; nunca en el correo diario. La persona las acepta o descarta.
- **FR-73** Un brief solo se crea a partir de resultados con revisión `closed_by_human`. Contiene `manifest.json`, `context.json`, `context.md`, `instructions.md` y figuras; cada parámetro, cifra y figura lleva su ID de evidencia.
- **FR-74** Los briefs se guardan en `data_dir/briefs/`, se copian a Obsidian (`Briefs/`) y a Drive (`DailyDigest/briefs/`) y se pueden descargar como zip desde la webapp. `digest brief <tipo> <result_id>` hace lo mismo desde la terminal.
- **FR-75** Un servidor MCP de solo lectura expone el registro a otros asistentes; no tiene herramientas de escritura y respeta `external_allowed` y las exclusiones.

## 4. Requisitos no funcionales

- **NFR-01** Un único usuario; servicio en un solo equipo Rocky Linux 9.
- **NFR-02** Recuperable: reinicios o repetición de intervalos no pierden revisiones ni duplican resultados.
- **NFR-03** Seguridad: invariantes de `AGENTS.md`; webapp solo en `127.0.0.1` tras Tailscale; sin puertos abiertos.
- **NFR-04** Trazabilidad: cada informe guarda modelos, versiones de prompt y evidencias usadas.
- **NFR-05** Captura de un proyecto típico en menos de 5 minutos; informe completo en menos de 60.
- **NFR-06** Idioma de la interfaz y de los informes: español.

## 5. Fuera de alcance

Generación de material docente, protocolos o artículos dentro del servicio (se hace fuera a partir de briefs; ver `EXTENSIONS.md`), ejecución de experimentos, captura de pantalla, agentes con shell libre, base vectorial, edición automática del tablero, dictado por voz (puede añadirse más tarde con transcripción local), multiusuario.
