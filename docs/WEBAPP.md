# Webapp de revisión (Dojo)

Webapp adaptable a móvil y ordenador, a la que se llega desde el enlace del correo. Reúne el informe completo, la revisión, el plan, el cuaderno personal de tareas, el historial y los disparos manuales, con vistas separadas para cada actividad.

## 1. Pantallas y rutas

| Ruta | Pantalla | Contenido | Acciones |
| --- | --- | --- | --- |
| `GET /` | — | Redirige al último informe | — |
| `GET /r/{fecha}` | Hoy | Informe diario completo; niveles técnico y de evidencias plegados; todo lo hecho con estado de revisión | Abrir resultado, marcar para revisar |
| `GET /r/{fecha}/res/{result_id}` | Detalle | Resumen, evidencias (con localizador), figuras, ejecuciones | Revisar este resultado |
| `GET /review/{result_id}` | Revisar | Resultado y figura; explicación automática oculta | Elegir modo, escribir |
| `POST /review/{result_id}/submit` | — | Guarda texto y encola `contrast` | — |
| `GET /review/{review_id}/result` | Contraste | Cuatro listas + errores del resumen, cada punto con su evidencia; ahora sí, explicación automática | Cerrar, requiere aclaración, posponer |
| `POST /review/{review_id}/decide` | — | Guarda decisión y dudas; entrega a Obsidian y Drive | — |
| `GET /plan/{fecha}` · `POST /plan/{fecha}` | Plan | Misión y calentamientos | Editar, aceptar |
| `GET /w/{AAAA-Wss}` | Semana | Informe semanal; pendientes por antigüedad | Elegir resultados para revisar |
| `GET /history?q=` | Historial | Informes por fecha, búsqueda en títulos y resúmenes | Abrir |
| `GET /generate` · `POST /generate` | Generar | Estado del último informe, de la cola y de cada canal | Generar ahora, ver avance, generar semanal |
| `GET /settings/models` · `POST /settings/models` | Modelos por tarea | Proveedores, modelos y orden por etapa | Guardar, volver al YAML por tarea o en conjunto |
| `POST /deliveries/{id}/retry` | — | Reintenta un canal (no inciertos) | — |
| `GET /opportunities` | Oportunidades (fase 6) | Propuestas de las extensiones con su motivo y resultados | Aceptar, descartar, crear brief |
| `POST /opportunities/{id}/brief` | — | Encola la creación del brief | — |
| `GET /briefs/{id}` · `GET /briefs/{id}.zip` | Brief (fase 6) | Contexto legible, instrucciones y figuras | Descargar zip, copiar instrucciones, abrir en Drive, anotar dónde quedó el contenido generado |
| `GET /manifest.webmanifest`, `/static/*` | — | PWA e iconos | — |
| `GET /healthz` | — | Estado del proceso y de la base | — |

El enlace del correo es `{web.public_base_url}/r/{fecha}`; el del semanal, `/w/{AAAA-Wss}`.

### Base disponible (WA-01)

`digest --config config.yaml web` abre la aplicación en `127.0.0.1:{web.port}`.
Están disponibles Hoy, Semana, detalle de resultados e Historial. Los enlaces
por fecha redirigen a `/reports/{id}`, que conserva la revisión exacta; el detalle
canónico es `/reports/{id}/results/{result_id}`. La revisión activa está disponible
en WA-02, el plan editable en WA-03 y Generar en WA-04.

Antes de mostrar un informe se vuelven a validar su contenido, completitud y
vínculo con las evidencias. Solo se sirven JSON de informes bajo `data_dir/reports`
y PNG generados que figuren en ellos. Consultar estas pantallas no crea la base
ni modifica informes o estados humanos. `/healthz` comprueba la apertura de SQLite
en modo lectura y el acceso al catálogo: devuelve 503 si falta o falla, sin
exponer detalles internos.

Historial pagina veinte revisiones. La búsqueda literal en títulos y resúmenes
se limita a las dos mil revisiones recientes y avisa si hay más; sin filtro se
puede seguir paginando. Los enlaces por fecha buscan primero en su día o semana
en la zona configurada. La PWA dispone de manifiesto e iconos locales y no cachea
informes. La sesión usa una cookie firmada `HttpOnly`/`SameSite=Strict` y el token
CSRF se vincula a ella; se rechazan cuerpos de más de 64 KB, orígenes ajenos,
identidades incorrectas y conexiones fuera de loopback.

Capturas de comprobación locales: `build/wa01-preview/mobile.png` (390 px) y
`build/wa01-preview/desktop.png` (1440 px), sobre una muestra retrospectiva de
fase 2. Son comprobaciones de navegador; el acceso desde un teléfono físico
se verifica en la puerta de fase y en el despliegue.

Al final del diario, «¿Quieres ampliar o comprobar algo?» (WA-08) abre
`/reports/<id>/followup`, vinculado a su revisión exacta. Permite buscar frases,
elegir hasta ocho y enviar una pregunta de hasta 2000 caracteres para explicar
o comprobar. Solo el POST guarda y encola; un GET no ejecuta nada.

`/followups/<id>` muestra el progreso y permite continuar un intento fallido.
La respuesta validada se abre en `/followups/<id>/rN`, con pregunta, frases,
explicación, comprobaciones, límites, procedencia y entregas por canal. Desde
esa ficha se reintenta un solo canal pendiente o fallido. El correo incierto no
tiene botón de reenvío. Las solicitudes repetidas no crean otro trabajo, y los
formularios ajenos a esa revisión se rechazan. La ampliación conserva originales,
planes y estados humanos. Contratos y límites en
[ON_DEMAND_FOLLOWUPS.md](ON_DEMAND_FOLLOWUPS.md).

## 2. Revisión

1. La pantalla Hoy destaca el resultado propuesto (`review/select.py`): el de mayor relevancia sin revisión abierta. Si hay una revisión abierta de días anteriores, se ofrece esa primero.
2. La persona elige el modo:
   - **Completo:** cuatro campos cortos: propósito, observación, límites, consecuencia.
   - **Breve:** tres frases guiadas: qué muestra, por qué importa, qué no sabes.
   - **Mínimo:** una duda en una línea o «posponer». No se contrasta.
3. Al enviar, el estado pasa a `submitted` y se encola `contrast`. La página consulta el estado cada cinco segundos con JavaScript propio hasta que llega el contraste; también ofrece un enlace para actualizar sin JavaScript.
4. Con el contraste visible (`contrasted`), la persona decide: `closed` → `closed_by_human`; `needs_clarification`; `postponed`. Las dudas escritas pasan como `origin = "review"` al plan siguiente.
5. Se escriben la ficha de Obsidian y la copia en Drive.

Reglas: ningún resultado se oculta por no estar revisado; nada se marca comprendido sin la decisión humana; no se crea una revisión nueva de un resultado con una abierta.

### Flujo disponible (WA-02)

El informe propone un resultado sin retirar los demás del inventario; una revisión
abierta tiene prioridad. Cada detalle permite «Revisar con mis palabras». El
formulario recibe `report_id` para fijar la revisión exacta y muestra título y
figuras, sin la ficha automática. Los campos enviados se guardan una sola vez:
un reenvío del formulario no crea otro trabajo y un texto distinto no pisa una
revisión abierta. Modos completo y breve exigen todos sus campos; el mínimo
guarda una duda o una decisión de posponer sin llamar al modelo.

El worker usa exclusivamente las evidencias del resultado y su ficha automática
validada. Aplica presupuesto, redacción de secretos y las políticas de todos los
proyectos que podría mencionar el texto humano; una política ausente bloquea el
envío a proveedores. El contraste pasa por esquema, referencias, cifras y cotejo
de fidelidad antes de guardarse como `contrasted`. Las categorías sin respaldo
y no verificable citan literalmente un campo humano, incluso si contiene una
cifra equivocada; no se inventan palabras atribuidas a la persona. La lectura
revalida y comprueba la vinculación del contraste con la explicación guardada.

`/review/{id}/status` ofrece un estado acotado para la consulta periódica.
`POST /review/{id}/retry` permite volver a encolar un contraste fallido sin
reescribir la explicación. Solo `POST /review/{id}/decide` puede cerrar la revisión:
antes del contraste únicamente se permite posponer. Si la persona pospone mientras
el modelo trabaja, la respuesta posterior no modifica esa decisión.

Los errores del resumen automático se señalan en el informe y en el detalle,
con enlace al contraste; el archivo original permanece intacto. La decisión y
las dudas se copian por un trabajo de entrega a Obsidian y Drive, con estado
independiente por canal. No se envía un correo adicional por cerrar una revisión.

## 3. Elegir y ajustar el próximo foco (WA-03)

`/plan` abre el plan del último diario; `/plan/AAAA-MM-DD` fija su fecha y
redirige a `/reports/{id}/plan`. Cada informe conserva su revisión exacta.
La selección vigente aparece primero, seguida de sus propuestas con motivo,
criterio y dependencia. Objetivo, balance conceptual y evidencias se pueden
abrir al necesitar más contexto. Las dudas humanas vigentes y los análisis
críticos del semanal aparecen como contexto, sin aceptarse como tareas.

Guardar un ajuste conserva acción, criterio y dependencia sin aceptar la
propuesta. Aceptar una misión diferente sustituye expresamente el foco vigente;
descartarla lo retira si estaba elegido. Se permiten hasta dos calentamientos,
también sin misión. Los cambios se envían a `POST /reports/{id}/plan` (o al alias
por fecha); el formulario incluye control de concurrencia y un identificador
que evita duplicados incluso después de otra decisión. Si cambió la selección,
el formulario obsoleto se rechaza con 409 y debe recargarse.

Cada acción conserva una instantánea en `/plans/{id}`. La siguiente generación
recibe la acción humana de `edited_text` y sus ajustes de criterio/dependencia,
sin cambiar las propuestas originales. La privacidad de los ajustes retiene
también los proyectos que después se retiran de la configuración. Un cambio
motivado del modelo sigue siendo una propuesta hasta otra acción humana.

El worker copia la instantánea exacta a Obsidian y Drive; no exporta una elección
posterior por error si la cola se procesa tarde. Formato aprobado por la persona
en [PLAN_ACCEPTANCE.md](PLAN_ACCEPTANCE.md). Las copias no se sobrescriben; cada
canal conserva su estado e intentos de forma independiente. No se envía correo
por elegir un foco y ningún resultado se marca comprendido por esa acción.

## 4. Generar y seguir la cola (WA-04)

`/generate` permite solicitar diario, semanal o avance. La web solo guarda la
petición; el worker captura, genera, valida y entrega. La primera petición puede
preparar la base del servicio, pero consultar la pantalla no la crea. Las tarjetas
se agrupan por estado con fecha de creación y acceso al detalle. Se muestran
cuarenta por página; los recuentos abarcan toda la cola y se puede abrir el resto.

`/jobs/{id}` muestra fechas, piezas guardadas, llamadas al modelo, enlace al
informe completo cuando valida y estados por canal. Los resultados de una
generación pendiente se pueden consultar en su inventario verificado, paginado
de cien en cien; no se muestra texto de modelo sin validar. El esquema con
flechas explica las etapas del servicio y los trabajos de entrega enlazan con su
informe de origen cuando ese trabajo consta en el registro. No es una estimación
porcentual. La consulta automática de estado ocurre cada cinco segundos, con
enlaces de actualización que funcionan sin JavaScript.

El identificador de formulario evita duplicar una solicitud incluso tras
terminar. Peticiones equivalentes sin límites explícitos reutilizan un trabajo
en cola o en curso; diario de web y temporizador comparten esa protección.
`--no-send` mantiene su propia petición y las revisiones con fechas explícitas
se conservan. Semanales automáticos y manuales mantienen distintas clases de
ventana porque sus cierres pueden diferir.

Un trabajo pendiente puede continuarse desde la web en su ventana e inventario
originales. Una revisión completa posterior impide reanudar un intento superado.
El proceso web no toma el bloqueo largo del worker: usa una transacción SQLite
corta para encolar y responde con el enlace al trabajo.

El reintento de `/deliveries/{id}/retry` afecta solo al canal pendiente o fallido,
también en las revisiones humanas. Los planes usan
`/plans/{id}/deliveries/{canal}/retry`, con el mismo criterio. Lo ya entregado se
conserva; el correo incierto no ofrece reenvío en la web. Destinos y canales se
obtienen del registro y de la configuración, no de campos libres del navegador.
Los parámetros y errores internos de jobs nunca se muestran en HTML ni JSON.

### Cuaderno de tareas (WA-09)

«Tareas» abre `/notebook`: tarjetas por estado o grafo con flechas desde la tarea
previa hacia su dependiente, zoom y enlaces a las fichas. Se puede buscar por texto
y filtrar por proyecto, estado, disponibilidad o prioridad mínima. Hasta 60 tareas
por página; las dependencias fuera de página se indican expresamente. Las tarjetas
se desplazan horizontalmente en móvil. No se cambia el estado arrastrándolas.

`/notebook/{proyecto}/{tarea}` muestra creación o seguimiento observado, prioridad
base, aumento aplicado, bloqueos y notas de origen separadas de «Mis notas y
ajustes». Guardar por POST añade una versión personal, con protección CSRF,
reenvíos idempotentes y rechazo de formularios obsoletos. No cambia Kanvas ni
declara comprensión. Las fichas retiradas de la captura conservan notas e historial.
El historial muestra 20 versiones por página y las evidencias, 50 por página.

`/notebook/settings` permite editar las reglas generales. El POST
`/notebook/refresh` solicita una captura al worker; abrir páginas no la ejecuta.
Las preferencias se usan en el siguiente plan diario, respetando privacidad y
dependencias. No cambian la prioridad de los jobs técnicos. Persistencia, límites
y fórmula en [PERSONAL_NOTEBOOK.md](PERSONAL_NOTEBOOK.md).

### Modelos por tarea (WA-06)

Desde Generar se abre «Elegir modelos por tarea». Cada etapa tiene un formulario
con los proveedores configurados: posición 1 para el primer intento, posiciones
posteriores para respaldos y 0 para excluir. No se admiten posiciones repetidas ni
una ruta vacía. El identificador del modelo admite hasta 200 caracteres: letras,
números y `._:/@+-`, con letra o número inicial. La misma regla se valida en YAML.
La interfaz permite hasta 24 proveedores; para listas mayores se usa YAML.

Guardar cambia solo esa etapa. Las opciones para volver al YAML por etapa o en
conjunto conservan el historial; se muestran las últimas 20 versiones. CSRF,
sesión, identidad, nonce y control de edición obsoleta protegen todos los cambios.
La web no muestra ni permite editar direcciones, nombres de variables de
credenciales o claves, y guardar no ejecuta una petición de prueba al proveedor.

Los trabajos en cola usan la selección vigente cuando empiezan. Los trabajos en
curso o reanudados mantienen su selección inicial; los valores nuevos no cambian
las piezas pendientes de ese trabajo. Si se retira un proveedor elegido, los
trabajos nuevos se bloquean hasta corregir la preferencia o volver al YAML. Si
cambia el destino de un proveedor ya fijado, se rechaza su reanudación; para usar
otra selección se solicita un trabajo nuevo sobre la ventana correspondiente.
La privacidad actual sigue aplicándose incluso a selecciones antiguas: excluir el
proveedor interno puede dejar sin proveedor elegible a un proyecto privado.

## 5. Diseño

- Una columna en móvil (≤ 640 px), dos en escritorio (contenido + panel de evidencias). Tipografía del sistema, tamaño base 17 px en móvil.
- Modo oscuro de bajo contraste por defecto por la noche (`prefers-color-scheme` y conmutador).
- PWA: `manifest.webmanifest` con nombre «Digest», iconos, `display: standalone`. Service worker opcional solo para la página sin conexión; no cachea informes.
- Figuras como miniaturas que se amplían al tocarlas.
- Sin dependencias de terceros en el navegador: JavaScript propio en `static/`,
  sin CDN; los formularios y enlaces funcionan sin JavaScript.

## 6. Seguridad

- Escucha solo en `127.0.0.1:{web.port}`. El acceso remoto lo da `tailscale serve` (ver `OPERATIONS.md`).
- Si la petición trae la cabecera de identidad de Tailscale (`Tailscale-User-Login`), debe coincidir con `web.allowed_tailscale_login`; si no coincide, 403. Verificar en la fase 0 que `tailscale serve` añade esa cabecera en la versión instalada.
- Formularios con token CSRF (doble envío: cookie `SameSite=Strict` + campo oculto).
- Cabeceras: `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- Plantillas Jinja2 con autoescape; Markdown con `markdown-it-py` (HTML desactivado) y `nh3`.
- Los SVG de los proyectos nunca se sirven: solo sus PNG rasterizados.
- El proceso web no ejecuta trabajos: inserta filas en `job` y responde. El worker los ejecuta con el mismo bloqueo que los temporizadores.
- Rutas de archivos servidas solo desde `data_dir/reports/` por ID, nunca por ruta recibida del cliente.

## 7. Respaldo en Obsidian

Si la webapp no está disponible, la ficha `Revisiones/AAAA-MM-DD-<result_id>.md` incluye un bloque para responder:

```markdown
---
result: res_proj-a_DV-03
estado: pendiente   # cambiar a «lista» para que se contraste
modo: breve
---
## Mi explicación
- Qué muestra:
- Por qué importa:
- Qué no sé:
```

El worker procesa la ficha solo si `estado: lista`, copia el texto a `review.human_text` y nunca reescribe esa sección; el contraste se añade en un archivo aparte `…-contraste.md`.

Al entregar un informe a Obsidian se crea la ficha del resultado propuesto si
todavía no existe y se conserva su vínculo con la revisión original. Solo se
importan esas fichas registradas (hasta doscientas recientes por pasada), con
lecturas acotadas a 32 KB. No se rastrean ni interpretan otras notas de la vault.
Un hash evita importar dos veces los mismos bytes. `modo` acepta `breve`,
`completo` o `mínimo`; los campos son los rótulos de su formulario. Para el modo
mínimo, `- Mi duda:` admite una duda o vacío para posponer. Cambiar `estado` a
`lista` envía la explicación, nunca declara comprensión ni cierra automáticamente.
El contraste se entrega tras la decisión humana; revisiones posteriores usan
`…-contraste-r2.md`, etc., conservando la ficha y los contrastes anteriores.
