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
