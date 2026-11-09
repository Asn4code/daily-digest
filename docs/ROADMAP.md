# Hoja de ruta

Siete fases. Desde la fase 1 se puede lanzar un informe a mano y recibir el correo; el semanal pertenece a la fase 2, la webapp a la fase 3 y la operación automática a la fase 4. Los IDs entre corchetes son los que asigna Kanvas al importar `docs/backlog.kanvas.json` en un tablero vacío.

Cada fase termina con su **puerta** (protocolo en `VALIDATION.md`, exigencias en `gates.toml`): la comprobación automática, la revisión de un agente distinto del constructor y tu firma. Las primeras tareas de cada fase dependen de la puerta anterior, así que el tablero no deja avanzar sin ella. Los criterios de «Aceptación» de cada fase son los que verifica su puerta.

| Fase | Grupo en Kanvas | Resultado visible para la persona |
| --- | --- | --- |
| 0 | Contratos y base (CB) | `digest doctor` confirma proyectos, proveedores, correo, Drive y Tailscale |
| 1 | Captura (CP) | `digest run` deja en el correo un informe mecánico con todo lo hecho; copia en Obsidian y Drive |
| 2 | Informe (IN) | Seguimiento de resultados y próximo foco; niveles móvil/vault; semanal con contraste crítico, todo validado |
| 3 | Webapp (WA) | Enlace del correo abre la webapp en móvil y ordenador; revisión activa; botones de generar |
| 4 | Operación (OP) | Temporizadores, copia remota completa, recuperación |
| 5 | Piloto (PL) | 7 a 10 jornadas reales, al menos un sábado; ajustes |
| 6 | Extensiones (EX) | Oportunidades en el semanal; briefs de protocolo y docencia para generar fuera; servidor MCP de solo lectura |

## Fase 0. Contratos y base

- [CB-01] Esqueleto del repositorio
- [CB-02] Configuración validada
- [CB-03] Esquema SQLite y migraciones
- [CB-04] Utilidades seguras de lectura y procesos
- [CB-05] Proyectos sintéticos de prueba
- [CB-06] Verificar contratos externos
- [CB-07] Puerta de fase 0

Aceptación: `make check` pasa; `digest doctor` lee los dos proyectos piloto y obtiene respuesta de Qwen3.6 y de NaN con datos sintéticos, sin modificar nada ni exponer secretos; los hallazgos quedan en `DECISIONS.md`.

## Fase 1. Captura, registro e informe mecánico

- [CP-01] Recolector de Kanvas
- [CP-02] Recolector de Git
- [CP-03] Recolectores de documentación y figuras
- [CP-04] Recolector de métricas
- [CP-05] Recolector de ejecuciones
- [CP-06] Resultados e intervalos
- [CP-07] Informe mecánico y digest run
- [CP-08] Correo esencial y copia en Obsidian y Drive
- [CP-09] Puerta de fase 1

Aceptación: escenarios T01, T02, T05–T11, T30; cambios conocidos aparecen una vez; `digest run` deja el correo en la bandeja con todas las tareas hechas y la copia en Drive.

## Fase 2. Informe multinivel con LLM

Base implementada antes del rediseño:

- [IN-01] Cliente LLM y enrutado con respaldo
- [IN-02] Esquemas, prompts y validador
- [IN-03] Informe diario multinivel
- [IN-04] Recolectores de notebooks, estructuras y sesiones de agentes
- [IN-05] Informe semanal

Rediseño D-047/D-048/D-049 aprobado; avance por tareas:

- [IN-07] Diagnóstico de rechazos y publicación sin sustitución mecánica — implementado
- [IN-08] Hechos normalizados y paquetes pequeños por fuente — implementado
- [IN-09] Nodos validados persistidos y generación reanudable — implementado
- [IN-10] Seguimiento diario de resultados y próximo foco, con niveles por canal — implementado
- [IN-12] Contraste crítico semanal de conclusiones y evidencia nueva — implementado
- [IN-11] Validación del flujo jerárquico con fallos y proyectos reales — muestras completas y cotejadas; firma humana en la puerta
- [IN-06] Puerta de fase 2: espera la nueva validación

Aceptación: escenarios T12–T18 adaptados al requisito vigente, sin referencias ni
cifras inventadas, con inferencias marcadas y sin sustituir secciones fallidas por
contenido mecánico. La persona debe poder explicar qué cambió y cómo afecta al
objetivo, contrastar evidencias y elegir o ajustar una misión con motivo,
dependencias y criterio de finalización. El mensaje móvil conserva condiciones e
incertidumbre; la vault permite profundizar en conceptos y técnica. El semanal
contrasta conclusiones previas con evidencia nueva y propone análisis que ayuden a
decidir, sin cambiar texto ni estados humanos. Arranque diferenciado de actividad
nueva y reutilización incremental comprobada; detalles en HIERARCHICAL_DIGEST.md.

## Fase 3. Webapp y revisión activa

- [WA-01] Webapp base: Hoy, detalle e historial
- [WA-02] Revisión activa y contraste
- [WA-03] Plan editable y dudas al plan
- [WA-04] Pantalla Generar y cola de trabajos
- [WA-05] Puerta de fase 3

Aceptación: T03, T04, T14, T19–T21, T25, T26; el enlace del correo abre el informe en móvil y ordenador; desde el móvil se revisa y se lanza un informe.

## Fase 4. Operación

- [OP-01] Unidades systemd y despliegue
- [OP-02] Acceso con Tailscale
- [OP-03] Copia remota completa, entregas y reintentos
- [OP-04] Copias de SQLite y restauración
- [OP-05] Puerta de fase 4

Aceptación: T22–T24, T27–T29; el sábado llega el semanal sin intervención; un reinicio no pierde revisiones ni duplica resultados.

## Fase 5. Piloto

- [PL-01] Piloto de 7 a 10 jornadas
- [PL-02] Evaluación y ajustes
- [PL-03] Puerta de fase 5

Medir: tiempo de lectura del correo (objetivo ≤ 1 min) y de la revisión (≈ 5 min); noches con revisión; cantidad y antigüedad de resultados pendientes; omisiones y afirmaciones sin respaldo en una muestra diaria; comparación Qwen3.6/NaN en el contraste. Decidir si activar `kanvas.write_enabled`.

Aceptación: las revisiones ayudan a registrar interpretaciones y decisiones, y mantener el sistema no exige rehacer el informe a mano.

## Fase 6. Extensiones

- [EX-01] Registro de extensiones y oportunidades
- [EX-02] Paquete de contexto y digest brief
- [EX-03] Extensiones de protocolo y docencia
- [EX-04] Oportunidades en el semanal y en la webapp
- [EX-05] Servidor MCP de solo lectura
- [EX-06] Extensiones de métodos y reunión de grupo
- [EX-07] Puerta de fase 6

Aceptación: T31–T35; un brief de protocolo y otro de docencia, generados desde resultados reales revisados, producen contenido útil al pasarlos a la herramienta elegida (Q-14). El orden de EX-03 y EX-06 puede cambiar según Q-13. Diseño completo en `EXTENSIONS.md`.

## Después (no planificado)

Escritura de propuestas en Kanvas; dictado con transcripción local; revisión semanal conceptual guiada; segundo modelo como revisor en casos seleccionados; búsqueda semántica si el volumen lo justifica; capacidad `draft` en extensiones muy usadas.
