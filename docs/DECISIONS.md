# Decisiones

Registro de decisiones de diseño. Una decisión no se reabre sin preguntar a la persona. Las nuevas se añaden al final con el siguiente número.

## Decisiones tomadas

| ID | Fecha | Decisión | Motivo |
| --- | --- | --- | --- |
| D-001 | 2026-11-04 | SQLite es la fuente de verdad; los archivos de informe son vistas | Trazabilidad, deduplicación y recuperación; el JSON de sesión diario perdía días sin revisar |
| D-002 | 2026-11-04 | El informe se entrega siempre; la revisión es opcional y nunca bloquea | Un día sin revisión no debe perder información |
| D-003 | 2026-11-04 | Informe diario (automático al final del día y manual) y semanal el sábado (automático y manual) | Petición de la persona |
| D-004 | 2026-11-04 | Sin prisa en la generación: hasta 60 min; el correo sale al terminar | Petición de la persona; permite varias pasadas y una llamada por resultado |
| D-005 | 2026-11-04 | Se muestran todas las tareas hechas, sin límite; la revisión propone una al día y permite más | Petición de la persona |
| D-006 | 2026-11-04 | Correo solo con lo esencial + enlace a la webapp; informe completo en la webapp | Petición de la persona |
| D-007 | 2026-11-04 | Webapp adaptable a móvil y ordenador, instalable como PWA, en `127.0.0.1` tras `tailscale serve` | Acceso desde el enlace del correo sin abrir puertos |
| D-008 | 2026-11-04 | Qwen3.6 para extracción por resultado; NaN para síntesis, plan y semanal; respaldo mutuo | NaN aplica retención cero y la persona no tiene reparos; mejor síntesis con modelos grandes |
| D-009 | 2026-11-04 | Interruptor `external_allowed` por proyecto, activado por defecto | Prever proyectos con datos de terceros |
| D-010 | 2026-11-04 | Kanvas solo se lee (`kanvas.json` por proyecto); escritura de propuestas tras el piloto | El tablero es de la persona; Kanvas pide no editar el JSON a mano |
| D-011 | 2026-11-04 | Copia remota continua en Drive con `rclone copy --immutable`, alcance `drive.file`, poda solo en `backups/` | Petición de la persona; nada se sobrescribe ni se borra |
| D-012 | 2026-11-04 | Validador obligatorio de IDs y cifras antes de publicar | Evitar afirmaciones inventadas |
| D-013 | 2026-11-04 | Revisión con contraste en cuatro categorías; nunca «comprendido» automático | La comprensión la declara la persona |
| D-014 | 2026-11-04 | Sin métricas de volumen (commits, archivos) en los informes | El objetivo es comprensión, no producción |
| D-015 | 2026-11-04 | Dictado por voz fuera del MVP; si se añade, transcripción local | El dictado del navegador puede enviar audio a terceros y exige HTTPS |
| D-016 | 2026-11-04 | Python 3.11, FastAPI, Jinja2, SQLite sin ORM, systemd con endurecimiento | Disponible en Rocky 9; poco que mantener |
| D-017 | 2026-11-04 | Temporizadores, botones y CLI solo encolan; un único worker ejecuta | Evita ejecuciones simultáneas y da un solo punto de bloqueo |
| D-018 | 2026-11-04 | El núcleo no genera contenido docente, protocolos ni métodos; detecta oportunidades y prepara briefs para generarlos fuera | Mantener el foco en comprender; el contrato estable es el paquete de contexto, no el generador |
| D-019 | 2026-11-04 | Funcionalidades nuevas como extensiones (contrato de EXTENSIONS.md §4, entry point `daily_digest.extensions`), en una fase 6 tras el piloto | Añadir tipos sin tocar el núcleo ni sus invariantes |
| D-020 | 2026-11-04 | Solo resultados con revisión cerrada por la persona alimentan un brief | No se enseña ni se comparte lo que aún no se ha entendido |
| D-021 | 2026-11-04 | Cada fase termina en una puerta: comprobación automática, revisión por un agente distinto y firma humana | Validar que cada etapa está bien construida antes de seguir |
| D-022 | 2026-11-04 | CB-01 usa setuptools para empaquetar `src/digest`, Typer en ejecución y pytest, ruff y mypy como extras de desarrollo; las demás dependencias previstas se incorporan al implementar sus módulos | Instalar y comprobar la base sin exigir servicios ni dependencias de fases posteriores |
| D-023 | 2026-11-04 | Configuración con Pydantic v2 estricto y PyYAML safe_load; lista ampliable de proyectos con IDs únicos, admitiendo una lista vacía | Petición de incorporar proyectos progresivamente; errores sin valores de entrada ni lectura de credenciales. PyYAML no ofrece tipos: solo su import tiene ignore_missing_imports y toda salida se valida con Pydantic |
| D-024 | 2026-11-04 | Elección inicial delegada por la persona: Qwen/Qwen3.8-27B interno para extracción, deepseek-v4-flash de NaN para síntesis, plan, semanal y contraste, con respaldo mutuo; modelos y routing editables en YAML, interfaz prevista en WA-06 | El Qwen coincide con OpenCode; NaN recomienda DeepSeek para razonamiento general. Es una selección provisional, no una comparación empírica; capacidades, credenciales y conectividad pendientes de CB-06 |
| D-025 | 2026-11-04 | Fixtures en directorios temporales nuevos, Kanvas vendorizado del commit fijado y aiosmtpd como dependencia de desarrollo | Construcción reproducible sin modificar proyectos reales; aiosmtpd implementa el doble SMTP exigido en TESTING.md, incluida la desconexión tras DATA |

| D-026 | 2026-11-04 | Q-06: Qwen interno Qwen/Qwen3.8-27B, URL en configuración privada, contexto anunciado 262144 en /models y salida JSON Schema probada | Verificado contra el servicio; límites de concurrencia y cuotas no anunciados, sin prueba de saturación. No se inventan límites operativos |
| D-027 | 2026-11-04 | Q-07: NaN en https://api.nan.builders/v1 con deepseek-v4-flash para síntesis, plan, semanal y contraste; catálogo y salida JSON Schema probados | Selección delegada por la persona en D-024; contexto 1M documentado por NaN. Cuotas y concurrencia dependen del proveedor y la cuenta, sin prueba de saturación |
| D-028 | 2026-11-04 | Q-08: Gmail por SMTP con contraseña de aplicación; cuenta del piloto en configuración privada | Elegido y configurado durante la conversación; autenticación y NOOP verificados sin enviar correo |
| D-029 | 2026-11-04 | Q-11: contraste inicialmente con NaN y respaldo interno, editable por configuración; comparar su utilidad durante el piloto | Elección inicial delegada por la persona y registrada en D-024; no implica que la calidad del contraste ya esté evaluada |

| D-030 | 2026-11-04 | Q-02: diario a las 20:00 y semanal el sábado a las 10:00, Europe/Madrid | Horarios aceptados expresamente por la persona; disponibilidad continua del equipo no confirmada |

| D-031 | 2026-11-04 | Q-01: Benchmark busca determinar hasta qué punto los predictores capturan los cambios estructurales y fisicoquímicos causados por mutaciones, distinguiendo la señal real de la variabilidad experimental, dinámica y entre predicciones, para delimitar qué conclusiones sobre su respuesta mutacional están respaldadas. | Objetivo confirmado por la persona; campañas y tareas son medios para responder esta pregunta |
| D-032 | 2026-11-04 | Q-01: VCD busca construir y validar una plataforma reproducible que permita pasar de una secuencia proteica a candidatos de cribado virtual priorizados, integrando modelado, cavidades, docking y dinámica molecular, con evidencia y controles que permitan juzgar la fiabilidad de cada etapa. | Objetivo confirmado por la persona; incluye utilidad científica y trazabilidad, además de desarrollo de software |

| D-033 | 2026-11-04 | Q-03: incluir Markdown e informes generados, además de tablas y figuras; inventario inicial en PILOT_SOURCES.md | Petición expresa de la persona; patrones y columnas se concretarán en CP-03/CP-04 con procedencia, límites y deduplicación |
| D-034 | 2026-11-04 | Q-05: incluir sesiones relevantes de Codex, OpenCode y Hermes en fase 2; no se indican otras herramientas | Aceptado por la persona; ubicaciones y formatos se verificarán antes del recolector, con extractos acotados y exclusión de secretos |

| D-035 | 2026-11-04 | Q-09: acceso móvil mediante Tailscale; la persona confirma que ya lo tiene instalado en el móvil | El equipo del servicio está conectado y MagicDNS verificado; la prueba de acceso móvil a informes se hará cuando exista la webapp, sin darla por realizada ahora |
| D-036 | 2026-11-04 | Q-10: usar el Drive personal de la persona, remoto gdrive: y carpeta DailyDigest | Confirmación expresa de la persona; carpeta preparada y acceso de lectura verificado por doctor |

| D-037 | 2026-11-04 | Q-14: usar Qwen y los modelos de NaN por defecto para generar contenido externamente desde los briefs; permitir solicitar generación o reelaboración con Claude o Codex | Preferencia expresa de la persona. Proveedor/modelo y herramienta son elecciones separadas; daily-digest prepara el contexto y la generación permanece fuera del núcleo. Rehacer conserva el original y el texto humano |

| D-038 | 2026-11-04 | Q-04: recoger logs, trazas e informes locales de las ejecuciones; SGE documentado en Benchmark y VCD, con Nextflow y ejecución local según la etapa. Consultas remotas posteriores solo de lectura; Slurm desactivado | Propuesta aceptada por la persona. La documentación identifica qsub vía samwise en Benchmark y perfiles SGE en VCD; disponibilidad y rutas exactas se verificarán en CP-05 sin ejecutar contenido de proyectos |
| D-039 | 2026-11-04 | Q-12: WeasyPrint como motor de PDF desde las plantillas HTML/CSS del servicio | Propuesta aceptada por la persona; instalación y validación de tablas largas, figuras, caracteres y paginación en CP-08. La versión se fijará tras comprobar compatibilidad; Chromium no es un respaldo automático |
| D-040 | 2026-11-04 | Q-13: priorizar briefs de protocolos reproducibles para la persona y colaboradores, en Markdown con pasos, parámetros, controles, criterios de éxito y problemas conocidos; después métodos para artículos | Propuesta aceptada por la persona. Docencia y reuniones se priorizarán según necesidades; se conserva el alcance de extensiones y se permite ajustar el orden de EX-03/EX-06 previsto en ROADMAP |

| D-041 | 2026-11-05 | Conservar DNS institucional gestionado por NetworkManager en el servidor; Tailscale se configura con accept-dns=false | Sistemas advirtió de posible interferencia con resolución IPA/Kerberos tras sustituir resolv.conf. La persona confirmó restauración de los DNS institucionales; resolución de la incidencia Kerberos y acceso móvil posteriores siguen por verificar. No se desinstala ni se cambia IPA por este ajuste |

| D-042 | 2026-11-05 | CP-03 incorpora Pillow para miniaturas PNG, CairoSVG para rasterizar SVG con recursos externos bloqueados y pypdfium2 para texto y primera página de PDF sin ejecutar contenido | Dependencias necesarias para informes y figuras de los proyectos, sin copiar SVG/PDF originales al registro de figuras. Dimensiones, páginas, bytes y textos acotados. No sustituyen WeasyPrint como generador de PDF en CP-08 |

| D-043 | 2026-11-05 | IN-01 incorpora httpx, previsto en el stack, para HTTP acotado con JSON Schema, timeouts y transporte inyectable; sin proxies heredados ni redirecciones | Pruebas sin proveedores reales; auditoría de metadatos sin cuerpos HTTP. Solo el proveedor llamado internal se considera interno: los restantes respetan external_allowed. |

| D-044 | 2026-11-05 | IN-04 incorpora nbformat, ya previsto en el stack, para leer celdas y salidas almacenadas sin ejecución | Se omiten HTML, JavaScript, widgets y salidas binarias; lectura, celdas y texto acotados. PDB/mmCIF se leen como metadatos, sin dependencia científica ejecutable. |

| D-045 | 2026-11-05 | La persona autoriza lectores SQLite acotados para OpenCode y Hermes, filtrados por proyecto | Conexión immutable de solo lectura, consultas fijas, máximo 200 filas y 500 000 pasos, texto acotado y sin copiar las bases. Se admite un archivo SQLite declarado de hasta 2 GB como excepción al tamaño de archivo textual; no se envía la base al modelo. WAL pendiente y cambios durante lectura se muestran como cobertura incompleta. |

## Preguntas abiertas

Las preguntas Q-01 a Q-14 tienen respuesta registrada en las decisiones. La fase 0 tiene revisión independiente y firma
humana registradas en `docs/reviews/phase-0.md`. Quedan verificaciones de implementación:

- CP-05: rutas y formatos de logs por proyecto y disponibilidad del acceso de solo lectura a SGE.
- CP-08: WeasyPrint 70 probado con fixtures e informe real; comprobaciones humanas de correo y copias aprobadas en la puerta de fase 1.
- Fase 2: verificar ubicaciones y formatos de sesiones de los agentes.
- Fase 3: probar el acceso móvil a la webapp con Tailscale.
- Fase 6: concretar cada brief y aplicar la prioridad protocolos → métodos,
  manteniendo las demás extensiones previstas.

Estas verificaciones no se consideran realizadas por haber elegido una opción.
Los límites operativos de proveedores que no se anuncian siguen sin darse por medidos.

## Hallazgos de verificación

Rellenar en CB-06 con lo comprobado (versiones, salidas reales, límites).

| Fecha | Componente | Hallazgo |
| --- | --- | --- |
| 2026-11-04 | Kanvas | Rama `cursor/standalone-html-board-6ccb`, commit `97e93ad` (27 oct 2026), versión 0.4.0. Tablero en `kanvas.json` por proyecto, esquema `"kanvas": 1`. Estados `proposed/todo/doing/review/done`. Notas con `at` y `by`. CLI con `check`, `status`, `list`, `show`, `batch`, `propose`, `note`, `--as`. `serve` invoca `status --json` internamente: confirmar su salida. |
| 2026-11-04 | OpenCode | Lectura de configuración local sin importar credenciales: modelo interno Qwen/Qwen3.8-27B; NaN con base https://api.nan.builders/v1 y deepseek-v4-flash disponible en la configuración. No es una comprobación de disponibilidad remota. |
| 2026-11-04 | NaN | [Guía de selección](https://nan.builders/docs/choose-a-model) recomienda deepseek-v4-flash para razonamiento general. [Ficha técnica](https://nan.builders/docs/models) declara contexto de 1M y json_schema en chat sin herramientas con limitaciones: la salida aún requiere validación local. No se ha hecho una llamada real. |
| 2026-11-04 | Kanvas local | La ayuda de status de la copia instalada 0.4.0 no anuncia --json. La copia vendorizada para fixtures ya se ha verificado contra 97e93ad3e62fdfcb3448b3b1d71efd755eeeef42; la procedencia de la instalación global no se presupone. No se ha cambiado el contrato del recolector. |
| 2026-11-04 | Fixtures CB-05 | make fixtures y doctor --offline pasan. 89 tests ejecutados dentro del sandbox y 91 tests completos confirmados por la persona con make check fuera del sandbox, incluidos SMTP normal y desconexión tras DATA. |
| 2026-11-04 | Piloto CB-06 | Doctor ejecutado contra benchmark y VCD: configuración, directorio local de datos, vault nueva y ambos kanvas check pasan. Configuración de máquina en config.yaml, excluida de Git. No se han modificado los proyectos. |
| 2026-11-04 | Drive piloto | Preparada la carpeta gdrive:DailyDigest con rclone mkdir como operación de configuración separada; después doctor confirma rclone lsd sin errores. No se han subido informes ni enviado correos. |
| 2026-11-04 | Pendientes CB-06 | Doctor no puede verificar los LLM ni SMTP por ausencia de credenciales en entorno/CREDENTIALS_DIRECTORY; Tailscale no está instalado. La fase sigue abierta y requiere además revisión independiente y firma humana. |
| 2026-11-04 | Proveedores CB-06 | Con autorización de la persona se reutilizaron las credenciales existentes de OpenCode/Hermes, sin mostrarlas ni incluirlas en Git. Guardadas en el directorio privado de credenciales del piloto; doctor las lee por CREDENTIALS_DIRECTORY. Qwen interno y deepseek-v4-flash devolvieron correctamente el JSON sintético validado. Pendientes SMTP y Tailscale. |
| 2026-11-04 | Tailscale CB-06 | Tailscale 1.104.5 instalado por la persona; BackendState=Running, equipo Online y MagicDNS activo. serve status responde sin configuración Serve; publicar la webapp se hará cuando esté implementada. No se ha activado Funnel. |
| 2026-11-04 | Cierre CB-06 | Doctor completo contra los dos proyectos piloto pasa: YAML, datos, vault, ambos kanvas check, JSON sintético validado por ambos LLM, autenticación SMTP sin envío, Drive y Tailscale. Límites de contexto internos no publicados en OpenCode: siguen sin verificación empírica; no se han dado por medidos. |
| 2026-11-04 | Catálogos LLM CB-06 | GET /models devuelve HTTP 200 en ambos proveedores. El catálogo interno identifica Qwen/Qwen3.8-27B con max_model_len=262144; el catálogo NaN incluye deepseek-v4-flash sin límite de contexto en esa respuesta. El 1M de NaN sigue siendo un valor documentado por el proveedor, no una prueba de saturación. |
| 2026-11-05 | DNS del piloto | Comprobado inicialmente resolv.conf generado por Tailscale. Después del ajuste indicado, la persona compartió resolv.conf generado por NetworkManager, búsqueda institucional y tres DNS internos. Procedimiento y límites de la comprobación en OPERATIONS.md, sección DNS institucional e IPA/Kerberos. |
| 2026-11-05 | Informe mecánico CP-07 | Captura, cola/worker serializado, agrupación y generación Markdown/HTML probadas contra fixtures sin entregas. Jinja2 (ya previsto en el stack) se incorpora para autoescape; markdown-it-py y nh3 se incorporan para el tratamiento seguro de Markdown en entregas. La validación de IDs de evidencia se ejecuta antes de publicar incluso en modo mecánico; la validación LLM completa sigue en fase 2. |

| 2026-11-05 | Entregas CP-08 | WeasyPrint 70 compatible con Pango local; PDF de fixtures generado y rasterizado para revisión visual. SMTP local y remoto rclone local prueban 40 tareas, figuras CID, reintentos independientes, estado incierto tras DATA, revisiones y protección de texto humano. Vista del correo a 390 px comprobada con Chromium; no equivale a comprobar un cliente de correo real. |

| 2026-11-05 | Revisión independiente CP-09 | Se reprodujeron y corrigieron ejecución de filtros Git, deduplicación incorrecta tras reapertura de una tarea y pérdida de omisiones persistentes de métricas. El revisor volvió a ejecutar sus reproducciones: corregidas; 132 tests pasan y los árboles de fixtures, incluido el índice Git, permanecen intactos. Ficha de fase 1 aprobada por la sesión independiente; firma humana pendiente. |

| 2026-11-05 | Cierre de fase 1 | La persona confirmó «revisado y aprobado» y marcó las tres comprobaciones humanas y la aprobación de fase. La puerta completa dio APROBADA (código 0). Se mantienen documentadas las limitaciones de cobertura del piloto. La fase 2 está autorizada mediante YOLO hasta IN-06. |

| 2026-11-05 | Formatos de sesiones IN-04 | Codex JSONL contiene session_meta/cwd y response_item/message; comprobados solo nombres de campos. OpenCode usa tablas session/message/part en una base de ~854 MB; Hermes sessions/messages en ~335 MB. No se leyeron mensajes para esta comprobación. Consultada la adaptación SQLite antes de implementarla, según AGENTS.md. |

| 2026-11-05 | Revisión de fase 2 | El revisor reprodujo fugas de secretos desde fuentes/contexto, bypass numéricos con unidades y puntuación, pérdida de etiqueta de interpretación semanal y reordenación de revisiones pendientes. Corregidos mediante frontera común de redacción y regresiones E2E de wire/almacenamiento, comprobación de tokens numéricos completos, marcado explícito y orden validado. Revalidación independiente y puerta en curso. |
