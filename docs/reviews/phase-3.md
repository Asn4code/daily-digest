---
phase: 3
builder: codex
reviewer: codex-independent-review_phase_three
verdict: aprobada
date: 2026-11-16
---

# Revisión de la fase 3: Webapp y revisión activa

Revisión independiente por la sesión `review_phase_three`, distinta de la
constructora. No he escrito código de producción ni modificado el tablero o
estados humanos. Alcance: funcionalidad de `a0eb3b1` y corrección del worker en
`877cabf`. Leídos AGENTS, SPEC, ARCHITECTURE, WEBAPP, TESTING, VALIDATION,
DECISIONS, ROADMAP y los contratos aprobados de plan y ampliaciones.

**Aprobada la capa técnica de revisión. La fase sigue pendiente de la firma
humana y de la puerta completa.** No se autoriza empezar la fase 4.

## Informe automático

Informe: [build/gates/phase-3.md](../../build/gates/phase-3.md).
Ejecutado por el revisor antes y después de la corrección del worker:

```bash
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/phase_gate.py 3 --no-manual
```

Ambas ejecuciones dan **PROVISIONAL (3)**, regresión incluida y todas las
comprobaciones automáticas PASS. Revisión/firma se omiten únicamente por
`--no-manual`. El constructor repitió la puerta sobre `877cabf` con el mismo
resultado. No se rebajaron gates ni se marcaron comprobaciones humanas.

Verificación independiente: `make check` completo, 467 tests PASS en 132,47 s,
con ruff, formato y mypy; después, las dos regresiones E2E del arreglo final del
worker y dos pruebas privadas del bucle PASS. El constructor ejecutó el conjunto
final completo: **469 tests PASS**, también con lint, formato y tipos.

Los intentos privados acumulados se reejecutaron juntos: **37 PASS en 9,25 s**.
Comandos y reproducciones en
[prechecks y revalidaciones](../../build/review-phase-three-precheck.md) y scripts
bajo `build/review-phase-three/`. Solo usan fixtures, transportes LLM falsos,
SMTP local/falso y remoto rclone local; no proveedores, proyectos personales ni
Drive reales.

## Comprobación completa posterior del constructor

El 2026-11-16 se ejecutó también la puerta con revisión y firma, sin
`--no-manual`. Todo pasa salvo «comprobaciones manuales», cuyas cuatro casillas
siguen vacías. El comando completo devuelve **SUSPENDIDA (1)** por esa firma
pendiente; el comando automático `--no-manual` devuelve **PROVISIONAL (3)**.
El informe enlazado refleja la ejecución completa más reciente. No hay fallos de
código ni se ha aprobado la fase o iniciado la siguiente.

## Requisitos funcionales y evidencias de cumplimiento

| Requisito | Implementación revisada | Verificación |
| --- | --- | --- |
| FR-30: lectura móvil/ordenador y PWA | `web/app.py`, plantillas, CSS/JS local, manifiesto e iconos; escucha loopback y URL privada configurada | `test_today_detail_history_and_pwa_are_local_read_only`; capturas Playwright finales a 390 px. Acceso físico/Tailscale e instalación quedan para la persona. |
| FR-31: Hoy, resultado, Revisar, Plan, Semana, Historial, Generar | Rutas canónicas por revisión en `web/app.py`, `web/store.py`, `web/jobs.py`, `planning.py` | `test_web_reading.py`, `test_active_review.py`, `test_plan_decisions.py`, `test_generation_queue.py`: pantallas, revisión exacta, paginación y búsqueda acotada. |
| FR-32: explicación propia previa y contraste | `review/select.py`, `records.py`, `contrast.py`; tres modos; cuatro categorías y correcciones; explicación automática ausente del formulario previo | `test_web_submit_hides_automatic_text_and_never_closes_without_decision`, modos completo/breve/mínimo, T25 y rechazo de cita humana inventada/contraste manipulado. |
| FR-33: decisión humana y dudas al plan | Solo la ruta POST de decisión llama al cierre en `review/records.py`; texto y dudas versionados; `report/daily.py` conserva procedencia y políticas | Pruebas de decisión explícita, intento de cierre antes del contraste, decisión durante generación, planes humanos conservados y privacidad histórica. |
| FR-34: retomar revisión abierta sin taparla | Selección prioriza abierta; submit transaccional impide sustituirla; ficha de Obsidian conserva vínculo y bytes | `test_open_review_prevents_replacing_human_text`, reenvío tardío del segundo formulario y T26; GET no crea revisiones ni cierra resultados. |
| FR-35: web solo encola | `queue.py`, POST de Generar/reanudar/reintentar y único worker serializado | Instrumentación que falla ante ejecución desde web; T03/T04, workers concurrentes, entrega por canal y rechazo de correo incierto. Arreglo final mantiene vivo el bucle tras un fallo registrado. |
| FR-36: ampliación de revisión exacta | `followups/selection`, `records`, `checks`, `generate`, `publish`; hash de origen, recibos fijados, evidencia nueva, cotejo y artefactos/correo ligados | `test_followups.py` y `test_followup_core.py`: original intacto, privacidad ancestral/retirada, falta de datos, datos cambiados, discrepancia, entradas repetidas, interrupciones, entrega incierta y tampering. |

También revisadas WA-06 (modelos por etapa y selección fijada por trabajo), WA-07
(Markdown literal seguro) y WA-09 (cuaderno personal). Sus pruebas cubren retorno
a YAML, caché/modelos efectivos, entidades/comillas, IDs iguales entre proyectos,
identidades reutilizadas, antigüedad acotada, bloqueos, historial, privacidad y
formularios concurrentes. No ejecutan contenido de proyectos ni aceptan planes
por decisión del modelo.

## Intentos deliberados e invariantes

- Identidad Tailscale incorrecta/duplicada, peer no local, Host ambiguo o ajeno,
  firma de cookie alterada, CSRF ausente/otra sesión/duplicado, Origin ajeno,
  `Sec-Fetch-Site: cross-site` y cuerpo por chunks superior a 64 KB: rechazados.
- Traversal, IDs inexistentes, JSON fuera de reports, symlinks de JSON/PNG,
  snapshots externos o modificados y base redirigida a un proyecto: rechazados.
  Solo se sirven figuras PNG del informe validado; no SVG de proyectos.
- XSS en fuente, salida de modelo y texto humano: escape o rechazo antes de
  publicar. CSP, nosniff, no-referrer, no-store y recursos propios verificados;
  Markdown conserva texto literal incluso con HTML habilitado por el visor.
- El único cambio a `closed_by_human` está en `review.records.decide`, invocado
  por POST humano protegido. Navegar, capturar, contrastar, ampliar o aceptar un
  foco no declara comprensión. El worker no pisa una decisión tomada mientras
  el modelo responde.
- Lecturas seguras/acotadas y T30, comandos por lista sin shell, Kanvas de solo
  lectura, paquetes delimitados y con presupuesto, validadores/certificados antes
  de servir o entregar, secretos redactados y ámbitos ancestrales conservados.
- Fichas humanas separadas de artefactos generados, instantáneas exactas y
  publicación inmutable; `rclone copy --immutable`. Horas UTC con presentación
  en la zona configurada; distinción entre evento y seguimiento observado.
- Correo de ampliación con identidad independiente, bytes ligados a revisión y
  última lectura verificada; incertidumbre persistida antes de DATA. Reintentar
  un canal no repite los enviados ni reenvía el incierto. Inventarios y resultados
  pendientes siguen accesibles, con paginación en vez de ocultación por estado.

## Capturas finales revisadas

Capturadas por esta sesión con Playwright y Chromium local sobre datos sintéticos
y el código final de interfaz, sin escrituras ni envíos:

- [Hoy a 390 px](../../build/review-phase-three/today-390.png).
- [Revisar a 390 px](../../build/review-phase-three/review-390.png).
- [Métricas y recursos del navegador](../../build/review-phase-three/browser-evidence.json).

Ambas vistas tienen ancho visible y scrollWidth de 390 px; texto y formularios
son legibles y no cargaron recursos externos. La pantalla Revisar conserva la
explicación automática oculta. Estas capturas satisfacen el intento de navegador
de VALIDATION; no sustituyen un teléfono físico ni la valoración de utilidad.

## Hallazgos

No quedan hallazgos bloqueantes o importantes abiertos. Correcciones reproducidas
y revalidadas durante los prechecks y la revisión formal:

- **Importante, resuelto:** `web/app.py:211`, `/healthz` afirmaba éxito sin base. Base ausente/corrupta devuelve ahora 503 genérico sin crear ni alterar archivos; regresiones de `test_web_reading.py`.
- **Importante, resuelto:** `review/records.py:98`, dos formularios idénticos con nonces distintos podían reabrir tras una decisión. Se registran ambas claves; `test_delayed_duplicate_from_second_form_cannot_reopen_a_decided_review` y reproducción privada pasan.
- **Importante, resuelto:** `planning.py:142`, una edición podía reducir ámbito de proyecto privado configurado pero no capturado. Se conserva la unión ancestral; regresiones de misión/calentamientos y prueba privada de proyecto retirado pasan.
- **Importante, resuelto:** `notebook.py:144`, tareas normales sin `deps` vaciaban el catálogo. Ausencia se normaliza a lista vacía y tipos inválidos siguen rechazados; snapshots naturales y pruebas privadas pasan.
- **Importante, resuelto:** `config.py:130`, el contrato YAML de modelo permitía valores que la página rechazaba fuera de su manejo de errores. ModelName se aplica también al proveedor YAML y los errores ocultan entradas; regresiones YAML y privadas pasan.
- **Bloqueante, resuelto:** `followups/checks.py:123`, tolerancia absoluta reproducía falsamente media histórica 5e-13 frente a real 2e-15. Comparación determinista exacta detecta discrepancia y reproduce el valor real; regresiones core/privada pasan.
- **Bloqueante, resuelto:** `followups/publish.py`, outbox con cuerpo alterado y mismos encabezados podía enviarse. Wire ligado a revisión, certificado y comprobado tras última lectura; pruebas de cuerpo/cambio tardío/aliases y reproducción privada pasan.
- **Bloqueante, resuelto:** `followups/publish.py:130`, PDF previo sin binding podía certificarse y copiarse. PDF se genera desde markup esperado, sus bytes se ligan antes de exponerlos y el manifiesto compara payloads esperados; pruebas de archivo ajeno, PDF no determinista e interrupción pasan.
- **Importante, resuelto:** `followups/records.py:37`, interrupción entre valor y hash dejaba binding irrecuperable. SAVEPOINT anidable revierte el par y permite reintento; regresión de autocommit y reproducción privada pasan.
- **Importante, resuelto en revisión formal:** `cli.py:150`/`worker.py:31`, un fallo normal registrado terminaba el único worker. JobFailure permite continuar con la captura siguiente y mantiene salida 1 de `--once`; dos regresiones E2E y dos privadas pasan, sin mostrar diagnóstico privado.

El detalle cronológico y los comandos de cada reproducción se conservan en el
[informe preparatorio](../../build/review-phase-three-precheck.md). Los antiguos
hallazgos abiertos que aparecen allí quedaron cerrados en sus revalidaciones;
no son problemas pendientes de esta ficha.

## Excepciones «gate: allow» revisadas

No hay excepciones en `src/` ni en el código funcional de esta fase. Las dos
anotaciones de `scripts/phase_gate.py:155` y `:212` están justificadas: el script
de calidad, fuera del núcleo desplegado, lanza comandos de comprobación y pytest
con listas de argumentos, sin shell, con timeout. No ejecuta contenido de los
proyectos observados. La puerta no registra WARN por excepciones funcionales.

## Veredicto del revisor

**Aprobada la revisión técnica independiente** de la fase 3 sobre `a0eb3b1` y
`877cabf`. Los requisitos funcionales revisados tienen implementación y pruebas,
los intentos adversariales están registrados y no quedan bloqueantes abiertos.

Quedan exclusivamente las comprobaciones y la decisión de la persona de la
sección siguiente: acceso real desde correo/móvil/ordenador, utilidad y duración
de revisión, y entrega solicitada desde móvil. No las infiero de las capturas ni
de pruebas con dobles. La puerta seguirá PROVISIONAL hasta su firma y la
comprobación completa; esta revisión no autoriza la fase 4.

## Firma de la persona

Comprobaciones que solo puedes hacer tú:

- [ ] El enlace de un correo abre el informe en el móvil y en el ordenador
- [ ] Una revisión completa desde el móvil lleva unos 5 minutos y el contraste es útil
- [ ] Desde el móvil se lanza un informe con Generar y llega el correo

- [ ] Apruebo la fase


## Cómo hacer las comprobaciones humanas

Para ejecutar la prueba manual antes del despliegue de fase 4, abre dos terminales
en la carpeta del repositorio. Mantén la web y el worker en primer plano:

```bash
# Terminal 1
CREDENTIALS_DIRECTORY="$HOME/.config/daily-digest/credentials" \
  .venv/bin/digest --config config.yaml web

# Terminal 2
CREDENTIALS_DIRECTORY="$HOME/.config/daily-digest/credentials" \
  .venv/bin/digest --config config.yaml worker
```

Si ya están en marcha con una versión anterior, reinícialos para cargar los cambios. El acceso móvil usa la URL privada de
`web.public_base_url`; si todavía no está disponible, consulta OPERATIONS.md §4 y
coordina el acceso con sistemas conservando `--accept-dns=false`. No abras el bind
a la red: la app escucha en 127.0.0.1.

Abre el enlace de un diario desde el correo en el teléfono y en el ordenador.
Confirma que puedes leerlo, abrir una evidencia y volver al informe sin perder
la revisión original. Sigue el acceso privado ya configurado; no cambies el DNS
institucional para esta prueba (OPERATIONS.md, apartado IPA/Kerberos).

En «Explicarlo con mis palabras», escribe una explicación breve, lee el contraste
y decide tú si cerrar, pedir aclaración o posponer. Valora si ayuda a entender el
resultado y cuánto tardas. No marques la casilla solo porque la página cargue.

Desde Generar solicita un diario y comprueba el correo recibido. Prueba también
«¿Quieres ampliar o comprobar algo?» al final de un diario: selecciona una frase,
pregunta qué permite concluir y espera la ampliación. Confirma que apunta a la
revisión elegida, conserva el original y muestra sus límites y comprobaciones.
Comprueba la nota en Ampliaciones y la copia en Drive followups, sin duplicados.

Como recorrido complementario, abre Tareas, cambia una prioridad y una nota,
consulta las dependencias y verifica su historial. En Generar → Elegir modelos
por tarea, guarda una elección y vuelve al YAML; comprueba que no pide claves.

Después marca únicamente las comprobaciones que hayas realizado y «Apruebo la
fase» si el conjunto te resulta útil. Con una duda o fallo, deja la casilla sin
marcar y describe qué ocurrió. La fase de operación espera esta aprobación.


## Incidencia de acceso durante la validación (constructor, 2026-11-16)

La persona comunicó que no había recibido correo. Se comprobó que las pruebas
recientes eran sintéticas, el registro piloto no tenía envíos recientes y la
configuración local conservaba dominio y login de ejemplo. No se dio por pasada
ninguna comprobación humana.

SMTP autentica con el directorio privado de credenciales. Se envió un único
correo técnico de acceso a la cuenta configurada: el servidor SMTP lo aceptó
como `sent`. Su asunto es «Daily Digest — comprobación de acceso a la webapp»;
es una muestra histórica R24 y no un diario nuevo ni prueba de recepción humana.

Para este ensayo se preparó `build/phase3-live/config.yaml` (ignorado por Git),
con la base de muestras de IN-11, puerto 8091 y dominio/login del propietario
de Tailscale. Los procesos temporales de web y worker usan esa configuración,
sin cambiar el DNS institucional ni desplegar unidades de fase 4. La muestra
R24 es de tipo avance histórico: sirve para probar lectura y revisión; las
ampliaciones requieren primero un diario generado desde Generar.

Tailscale devuelve «Serve is not enabled on your tailnet». Falta que la persona
habilite Serve desde su cuenta; después se puede enlazar el servicio privado.
`CorpDNS=false` sigue activo. El acceso desde móvil y las cuatro casillas de
firma permanecen pendientes.


### Acceso privado preparado (constructor, 2026-11-16)

La persona habilitó Serve en su cuenta y ejecutó la configuración con sudo.
El proxy privado HTTPS apunta al puerto local 8091. Se verificó respuesta 200
del informe R24 por HTTPS con certificado válido. En el servidor se usó una
resolución puntual de la petición, sin cambiar hosts ni DNS del sistema.

Después del cambio, `CorpDNS=false` y los tres DNS institucionales de
NetworkManager siguen intactos. El acceso desde el teléfono o el ordenador
requiere su conexión a Tailscale. Las comprobaciones de la persona siguen
pendientes; una respuesta HTTP del constructor no firma esas casillas.


### Navegador en el propio servidor

La persona aclara que el navegador del ordenador se usa en el servidor. Con
`accept-dns=false`, su DNS institucional no resuelve el nombre privado de la
tailnet. Para el ensayo local está disponible
`http://127.0.0.1:8091/reports/rep_in11_daily_levels_r24`; el móvil conserva el
enlace HTTPS privado. Esta alternativa no cambia DNS, hosts ni el bind loopback.
Debe quedar registrada la ruta realmente comprobada por la persona al validar
acceso y evidencias; no se infiere el cumplimiento de la casilla completa.


### Confirmación humana de acceso parcial (2026-11-16)

La persona confirmó primero que el informe se abre en el móvil. Después de
identificar que el navegador del ordenador corre en el servidor, confirmó
«sí, se abre y puedo consultar una evidencia» por la URL local. Consta acceso
funcional en ambos contextos y consulta de evidencia en el servidor.

Se mantienen vacías las casillas originales: la apertura del enlace del correo
en ambos dispositivos y la recepción humana aún no se han confirmado de forma
literal. No se infieren de SMTP `sent` ni del acceso por enlaces del chat. La
revisión activa y la generación desde móvil pueden comprobarse a continuación.

### Ampliación aprobada: seguimiento solicitado (WA-10, 2026-11-16)

La persona aprobó el diseño y formato de `docs/WATCHLIST.md` en el tablero y el
chat. Se implementó en `df8cdf7`, sin interpretar esa aprobación como firma de
fase ni cierre de revisión humana. La revisión adicional independiente está en
[wa-10.md](wa-10.md), aprobada técnicamente por una sesión ajena a la construcción.
Conserva el alcance histórico del veredicto anterior y registra dos correcciones
revalidadas: comparación en días estables e historial de temas pendientes.

`make check`: 493 pruebas pasan, incluidos 24 casos de seguimiento. El revisor
añadió cinco comprobaciones privadas y capturas de lista, ficha e informe a
390 px, sin desbordamiento. Los ejemplos científicos usan fixtures; no son
resultados ni conclusiones de los proyectos piloto.

La web y el worker temporales del perfil `build/phase3-live/config.yaml` se
reiniciaron para cargar el código nuevo en el mismo puerto 8091. No hay jobs
ejecutándose al comenzar ese reinicio. Se verificó `/watchlist` localmente y
se mantuvo intacto `/etc/resolv.conf`; no se reconfiguró Tailscale ni el DNS.

Comprobación humana adicional pendiente: abrir «Seguimiento», pegar los tres
temas de benchmark, indicar su ID de proyecto y revisar antes de guardar;
editar una prioridad y consultar el historial. En una próxima generación,
comprobar que el resumen del móvil y el detalle conservan preguntas, evidencias,
límites y temas sin respuesta. Los informes anteriores no se modifican.

### Corrección tras la prueba humana del formulario (2026-11-16)

La persona abrió Seguimiento y obtuvo «Solicitud no autorizada o no válida» al
pulsar «Revisar lista». La prueba con navegador nativo encontró un fallo que las
pruebas ASGI y las capturas estáticas no detectaban: `no-referrer` producía
`Origin: null` en Chromium y el middleware rechazaba el formulario legítimo.

`9ecad51` usa `Referrer-Policy: same-origin`, mantiene el origen exacto y el
token CSRF obligatorios y separa cookies de las dos instancias locales. El
constructor y el revisor independiente probaron el formulario en Chromium
contra la web temporal, también después de abrir la otra instancia: vista previa
200 con cookie y Origin exacto, sin guardar temas. La revisión adicional está
en [browser-forms.md](browser-forms.md); confirma además rechazo de orígenes,
tokens e identidades ajenos y ausencia de Referer al navegar a otro origen.

La web temporal 8091 ya carga la corrección; hay que volver a cargar la página
para renovar la sesión antes de enviar un formulario anterior al reinicio.
`make check`: 496 pruebas pasan, lint, formato y tipos correctos. Puerta 3
`--no-manual`: PROVISIONAL (3), todo automático PASS. El DNS institucional sigue
intacto. La repetición humana del envío y las firmas de fase siguen pendientes.

### Confirmación humana del formulario corregido (2026-11-16)

Tras recargar y repetir el formulario, la persona confirma «hecho y funciona».
La consulta de solo lectura del perfil de validación encuentra una ficha activa
guardada para `benchmark`: «Aumento de semillas por modelo». Queda comprobado
el flujo de entrada y guardado en ese equipo; no se infiere que se hayan añadido
los otros temas, editado prioridades o validado el seguimiento en un informe.
La revisión activa, generación/recepción y firma de fase conservan sus pendientes.

### Ensayo con dos preguntas humanas (2026-11-16)

La persona añade también «Errores frente a cristales», conserva activo
«Aumento de semillas por modelo» en benchmark y pide pasar al informe.
El avance actual, trabajo 1 del perfil temporal, queda pendiente como
`rep_preview_2026-11-16_r1`: 2649 evidencias de arranque y sesenta resultados
históricos, sin resultados actuales, con cobertura parcial. Los paquetes de
ambas preguntas exceden el límite antes de llamar al modelo; no se envía ni
se considera completo. El borrador y el inventario se conservan.

Se propone WA-11 en `docs/WATCHLIST_SCALING.md` para abordar esa limitación
sin elevar límites ni recortar fuentes silenciosamente. Aún requiere aprobación
y no se ha implementado. La comprobación automática anterior corresponde al
código revisado; no resuelve este bloqueo descubierto en la validación real.

Para revisar el flujo se inicia además el trabajo 2, un avance retrospectivo
del 2026-11-09 05:00–16:00 UTC. El intervalo contiene dieciocho evidencias de
evento sobre cosecha, ampliación de semillas y comprobaciones contra cristales.
Se mantienen fechas y todos los resultados de ese intervalo; no representa
actividad del 16 de noviembre. Las preguntas actuales quedan fijadas y no se
entrega ni cierra el intervalo. Su resultado y revisión independiente se
registrarán al terminar; esta nota no declara que ya haya un informe completo.


### Escalado aprobado y correcciones de procedencia (2026-11-17)

La persona aprobó WA-11 en el tablero y en el chat el 16 de noviembre. Se ha
implementado la propuesta: hojas coherentes acotadas, reutilización de fuentes
validadas, reducción por niveles y manifiesto de padres e inventario exactos.
La revisión independiente de [WA-11](wa-11.md) está aprobada técnicamente;
conserva la cobertura parcial y los casos indivisibles que exceden el presupuesto
como pendientes, sin recortar fuentes ni elevar límites. La prueba sintética de
2600 evidencias no acredita completitud de la captura real de arranque.

El ensayo retrospectivo con las dos preguntas continúa en el trabajo 3, con
`glm5.3-flash` para extracción, contexto y cotejo, conservando su inventario,
intervalo y preguntas. No se envía ni representa el estado del 17 de noviembre.
Una revisión anterior obtuvo evaluación y cotejo válidos para cristales, pero no
completó el informe. El diagnóstico permitió corregir falsos rechazos de fechas
ISO e identidades Git/etiquetas de lote; sus revisiones independientes están en
[provenance-timestamps.md](provenance-timestamps.md) y
[source-identifiers.md](source-identifiers.md). Los hallazgos del primer intento
se documentan como corregidos, sin borrar las reproducciones.

La validación del informe exacto, la comprobación humana y la firma de fase
siguen pendientes. Ninguna de estas revisiones técnicas marca comprensión humana
ni autoriza publicar un informe incompleto.


### Presupuesto de reparaciones (2026-11-17)

La primera suite completa estable tras WA-11 pasó 573 pruebas. El prompt
`source` v10, que pide fuentes más concisas conservando cifras decisivas,
expuso después tres fallos de presupuesto en reparaciones de extracción:
las instrucciones adicionales podían hacer superar los 24 000 caracteres.
El router comprueba ahora el mensaje completo antes de cada intento de fuente,
síntesis y cotejo; si la reparación no cabe, conserva el paquete original para
el respaldo o deja el nodo pendiente. No aumenta límites ni elimina evidencias.
Las pruebas cubren la frontera exacta, Unicode, respaldo permitido/privado y
un primer mensaje excesivo. La validación final y la revisión independiente
se registran en sus notas; no se reutiliza el resultado anterior para aprobar
este cambio.

La web temporal en 8091 está actualizada y responde tanto por localhost como
por HTTPS privado. Se verificó que `/etc/resolv.conf` mantiene exclusivamente
los DNS institucionales. La cola temporal atiende nuevas solicitudes sin
reencolar automáticamente los ensayos históricos fallidos; no sustituye el
despliegue systemd pendiente de fase 4.


### Resultado automático actualizado (2026-11-17)

Sobre `db0921e`, `make check` pasa: lint, formato, mypy estricto y **575 tests**
(228,51 s), sin omisiones. La puerta `phase_gate.py 3 --no-manual`, ejecutada
con `.venv/bin` en PATH, da **PROVISIONAL (3)**: archivos, reglas, herramientas,
escenarios y tablero pasan. La revisión adicional de
[repair-message-budget.md](repair-message-budget.md) aprueba técnicamente las
seis invocaciones de generación/cotejo, con 88 pruebas focalizadas.

WA-11 está terminada en Kanvas y WA-05 vuelve a estar en curso. El trabajo real
3 mantiene sus evidencias y preguntas fijadas y continúa sin entrega. No se
marca como informe completo mientras haya fuentes sin validar ni se firma la
fase. La cola temporal conserva fallidos los trabajos 1/2 sin reencolarlos.


### Resultado del ensayo y bloqueo numérico (2026-11-17)

El trabajo 3 terminó pendiente en `rep_preview_2026-11-09_r7`. Conserva
la evaluación de cristales y su cotejo válidos; varias extracciones se rechazaron
por comprobación numérica y el respaldo agotó tiempos de espera. La evaluación
de semillas no terminó antes del límite global. No hubo entrega ni informe
final nuevo. Las referencias previas a «sigue ejecutándose» describen el estado
anterior y no su resultado final.

Se inicia una comprobación privada de las evaluaciones de seguimiento por
separado, con el mismo inventario, intervalo, preguntas y modelos congelados.
Las otras etapas quedan expresamente pendientes; el artefacto no se registra
como informe completo ni se entrega.

El diagnóstico sintético de `NUMERIC_VALIDATION.md` reproduce cinco rechazos
indebidos de prosa respaldada. WA-12 propone corregirlos mediante tratamiento
común de formato, IDs y cantidades, conservando pruebas adversariales de unidades
inventadas y rangos mal interpretados. Sigue propuesta y requiere aprobación;
WA-05 depende de ella. Las 575 pruebas y la puerta provisional anteriores no
validan esta propuesta ni resuelven estos casos nuevos. Producción permanece
sin cambios respecto a `15e63bc`.


### WA-12 aprobada e implementación en revisión (2026-11-17)

La persona aprobó WA-12 en el tablero y confirmó «hecho». La puerta se pausa
mientras se termina esta corrección. La vista numérica común conserva originales,
IDs y dimensiones y vincula relaciones/anotaciones en una fuente citada, con
pruebas adversariales. El primer recorrido completo pasó 627 pruebas; una
segunda ejecución durante cambios de huella de caché no reutilizó nodos, y la
reproducción aislada estable pasó. Se ejecuta de nuevo la suite sobre código
estable; no se rebaja la exigencia de caché ni se omite la prueba.

La muestra privada aislada llegó a tener ambas evaluaciones y cotejos automáticos
válidos, pero su revisión independiente encontró R1–R4 y la rechazó. Ver
[watchlist-real-sample.md](watchlist-real-sample.md), que conserva la identidad
exacta sin publicar datos científicos de los proyectos. Se refinan instrucciones
y se añade una capa específica de cotejo; los tests simulan rechazo, reparación
y reauditoría de caché. Una muestra nueva está en generación y debe revisarse de
nuevo. No se acepta la anterior, no se entrega y no se firman casillas humanas.


### Estado técnico y reanudación (2026-11-19)

WA-12 terminó técnicamente con `make check`: **698 pruebas** y revisión
independiente en `wa-12.md`. La puerta automática tras su cierre dio
**PROVISIONAL (3)**; firmas humanas intactas. La evaluación histórica de cristales
se aceptó en una segunda muestra exacta, con alcance limitado y sin aprobar el
resto: su identidad y veredicto constan en `watchlist-real-sample.md`.

El ensayo comparativo 4 usa una selección independiente y congelada de modelos,
con inventario/hash, preguntas y ventana idénticos a los anteriores; no modifica
los modelos de los trabajos 1–3 ni las preferencias globales. Se retoma tras una
interrupción de sesión, sin captura nueva ni entrega. La configuración privada
se reserializó con sus alias publicados; sus valores y modelos no cambiaron.

El rechazo de un fragmento numérico por omitir una nota de procedencia motivó el
ajuste revisado en `annotation-omission.md`. Mantiene dimensiones y asociaciones,
y conserva como pendientes las notas que no puede interpretar con seguridad.
La suite final y la nueva revisión exacta del informe se registrarán por separado;
no se considera completo por tener una extracción o evaluación válida.

### Verificación del ajuste y comparación de modelos (2026-11-19)

El código estable de `3b98404` pasa `make check`: **724 pruebas**, lint, formato
y tipado estricto. La revisión independiente del ajuste queda anclada a ese
commit en `annotation-omission.md`: 429 pruebas focalizadas, incluidos ataques
privados. La nueva puerta automática de fase 3 pasa sus comprobaciones y sigue
**PROVISIONAL (salida 3)**; no sustituye la validación real ni la firma humana.

El trabajo 4 acumula tiempos de espera y rechazos de cantidades o asociaciones
no respaldadas. No se rebaja el validador para completarlo. Una extracción
sintética con `deepseek-v4-flash` de NaN produjo JSON conforme al esquema en
unos 18 segundos; esto solo comprueba esquema y latencia, no fidelidad científica.
Se prepara una comparación independiente con ese modelo, el mismo inventario
histórico y las mismas preguntas, sin entrega ni cambios de preferencias
globales. Su resultado se registrará cuando termine. El trabajador temporal de
cola se detuvo para evitar que recapture el inventario de esa comparación.

El trabajo 4 terminó pendiente en `rep_preview_2026-11-09_r9`; ninguna de las
dos evaluaciones de seguimiento quedó completa. Se inició el trabajo 5 con una
selección congelada independiente de DeepSeek y se comprobó que su hash de
inventario coincide exactamente con el original. Su primer arranque no recibió
`CREDENTIALS_DIRECTORY` y quedó pendiente sin llamar a proveedores; se reanudó
con la ruta habitual de credenciales, sin copiar secretos a la configuración.
La primera extracción y su cotejo automático pasaron en unos 27 segundos en
total. Las restantes fuentes y evaluaciones siguen en ejecución; esto no aprueba
el informe. Se restauró la cola temporal después de que el ensayo adquiriera
su bloqueo, manteniendo fallidos los ensayos anteriores.

### Hallazgo de alcance en la extracción y corrección (2026-11-19)

La revisión independiente de una extracción del trabajo 5 encontró SF1 pese al
cotejo automático positivo: una decisión de si aceptar cambios de protocolo se
transformó en una aceptación obligatoria para acciones heterogéneas. La candidata
queda rechazada e identificada en
[source-decision-scope.md](source-decision-scope.md); el detalle científico
permanece privado. Se interrumpieron ensayo y cola temporal sin entrega, dejando
el trabajo con error técnico `worker_interrupted`, sin modificar estados humanos.

Conforme a VALIDATION.md §1 se corrige el hallazgo antes de continuar la puerta:
source v11 y grounding v8 conservan la elección pendiente, la acción y el
subconjunto al que corresponde cada requisito. Ocho pruebas de fidelidad pasan,
incluido bloqueo o reparación en tres campos de extracción; la revisión
independiente considera pertinente la mitigación. La nueva puerta automática
sigue PROVISIONAL con todas sus comprobaciones técnicas aprobadas. Falta la
suite completa y, separadamente, comprobar la eficacia en una candidata real
nueva. No se acepta retrospectivamente la muestra rechazada ni se firma la fase.

La primera suite del ajuste terminó con 723 pruebas aprobadas y siete fallos del
semanal: al crecer el prompt de fuente, una unidad completa dejó de caber en
24 000 caracteres (`coherent_unit_budget_exceeded`). Se compactó source v11
conservando sus controles, hasta 3652 caracteres frente a los 3816 de v10;
no se elevaron presupuestos ni se dividieron fuentes coherentes. La reproducción
focalizada del semanal y fidelidad pasa sus 15 pruebas. Se repiten suite y puerta
sobre el texto estable; ese primer resultado no se presenta como aprobación.

Verificación final del ajuste compacto: `make check` pasa **730 pruebas**
(213,66 s), lint, formato y tipado. La puerta de fase 3 vuelve a dar PROVISIONAL
(3), con todas las comprobaciones automáticas aprobadas. La revisión independiente
confirma equivalencia de los controles previos y mitigación de SF1 en
`source-decision-scope.md`, con la huella exacta del prompt. Se inicia una
comprobación privada centrada en las fuentes de la candidata rechazada, con
inventario y selección de modelos del trabajo 5; las demás etapas se mantienen
expresamente pendientes y el artefacto no se cataloga ni entrega como informe.

El ajuste y la revisión se publicaron en `ce1b1b7`. En la comprobación privada,
la primera respuesta de NaN se rechazó por `unsupported_number` en una observación
y la reparación agotó su plazo; se está probando el respaldo configurado.
La mitigación de SF1 todavía no tiene una candidata real nueva aprobada.
La cola temporal está de nuevo disponible y no recupera los ensayos fallidos;
la web responde en 8091 y se verificaron intactos los DNS institucionales.

### Diagnóstico de la prueba aislada y modalidad (2026-11-19)

La prueba anterior terminó en el artefacto privado
`build/phase3-live/source-only-4d5dc4306514496982ef3fce934d0546.json`, sin fuentes
completas. Una comprobación posterior de una sola pieza conservó respuestas
exactas y terminó también pendiente. El diagnóstico reproduce dos rechazos:
cambiar una etiqueta de recuento y omitir una anotación numérica de la fuente.
El fragmento literal completo valida con el código actual; no se modifica el
validador para aceptar la versión abreviada o la etiqueta sustituida.

La revisión científica rechaza además la candidata de reparación: convierte vías
posibles y una condición de una rama en requisitos generales, y afirma cierre
desde artefactos sin respaldo suficiente. Se precisan source v12 y grounding v9
para conservar modalidad, decisiones y alcance; la cita numérica mantiene su
anotación íntegra. Source sigue por debajo del tamaño de las versiones anteriores.
Las regresiones focalizadas pasan 169 pruebas, incluido el semanal; se ejecutan
suite completa y puerta sobre el texto definitivo. Falta comprobar otra salida
real, sin entregar ni alterar las firmas humanas.

Verificación final de source v12 y grounding v9: `make check` pasa **737 pruebas**
(228,85 s), lint, formato y tipado estricto. La puerta automática de fase 3 da
PROVISIONAL (3), con todas las comprobaciones técnicas aprobadas. La revisión
independiente de `source-decision-scope.md` registra hashes y conserva el rechazo
de la candidata anterior; sus 14 pruebas específicas pasan. Una nueva
comprobación aislada está en marcha y conserva las respuestas para diagnóstico.
Estos resultados técnicos todavía no aprueban otra candidata científica ni el
informe completo.

### Citas completas y plazo del ensayo (2026-11-20)

La comprobación v12 terminó pendiente sin fuentes válidas. La revisión técnica
de los dos puntos recomienda conservar el literal completo: una lista de palabras
no demuestra que el signo no represente una dimensión o relación. Source v13
pide mantener completo el contexto entre paréntesis y tras dos puntos; el
validador, router, límites y formatos permanecen intactos. Doce regresiones
conservan el rechazo de pérdida de unidades, operandos o etiquetas.

`make check` pasa **749 pruebas** (211,83 s), lint, formato y tipado. La puerta
automática de fase 3 da PROVISIONAL (3), con todas sus comprobaciones técnicas
aprobadas. La revisión independiente en `colon-literal-scope.md` aprueba el
ajuste técnicamente y ejecuta 41 pruebas focalizadas; no aprueba la salida real.

El nuevo arnés privado usa los 60 minutos configurados, frente a los veinte del
ensayo anterior, sin elevar el límite del servicio. La primera salida conservó
el fragmento completo, pero al reparar otros campos lo volvió a abreviar y quedó
rechazada; se prueba el respaldo configurado. No hubo entrega, nueva captura ni
cambios de comprensión humana. El inventario y los modelos congelados siguen
siendo los del trabajo 5.
