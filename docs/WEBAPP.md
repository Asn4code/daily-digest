# Webapp de revisión (Dojo)

Webapp adaptable a móvil y ordenador, a la que se llega desde el enlace del correo. Reúne el informe completo, la revisión, el plan, el historial y los disparos manuales. No muestra el tablero ni el IDE: una cosa cada vez.

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
| `POST /deliveries/{id}/retry` | — | Reintenta un canal (no inciertos) | — |
| `GET /opportunities` | Oportunidades (fase 6) | Propuestas de las extensiones con su motivo y resultados | Aceptar, descartar, crear brief |
| `POST /opportunities/{id}/brief` | — | Encola la creación del brief | — |
| `GET /briefs/{id}` · `GET /briefs/{id}.zip` | Brief (fase 6) | Contexto legible, instrucciones y figuras | Descargar zip, copiar instrucciones, abrir en Drive, anotar dónde quedó el contenido generado |
| `GET /manifest.webmanifest`, `/static/*` | — | PWA e iconos | — |
| `GET /healthz` | — | Estado del proceso y de la base | — |

El enlace del correo es `{web.public_base_url}/r/{fecha}`; el del semanal, `/w/{AAAA-Wss}`.

## 2. Revisión

1. La pantalla Hoy destaca el resultado propuesto (`review/select.py`): el de mayor relevancia sin revisión abierta. Si hay una revisión abierta de días anteriores, se ofrece esa primero.
2. La persona elige el modo:
   - **Completo:** cuatro campos cortos: propósito, observación, límites, consecuencia.
   - **Breve:** tres frases guiadas: qué muestra, por qué importa, qué no sabes.
   - **Mínimo:** una duda en una línea o «posponer». No se contrasta.
3. Al enviar, el estado pasa a `submitted` y se encola `contrast`. La página consulta el estado cada pocos segundos (htmx) hasta que llega el contraste.
4. Con el contraste visible (`contrasted`), la persona decide: `closed` → `closed_by_human`; `needs_clarification`; `postponed`. Las dudas escritas pasan como `origin = "review"` al plan siguiente.
5. Se escriben la ficha de Obsidian y la copia en Drive.

Reglas: ningún resultado se oculta por no estar revisado; nada se marca comprendido sin la decisión humana; no se crea una revisión nueva de un resultado con una abierta.

## 3. Diseño

- Una columna en móvil (≤ 640 px), dos en escritorio (contenido + panel de evidencias). Tipografía del sistema, tamaño base 17 px en móvil.
- Modo oscuro de bajo contraste por defecto por la noche (`prefers-color-scheme` y conmutador).
- PWA: `manifest.webmanifest` con nombre «Digest», iconos, `display: standalone`. Service worker opcional solo para la página sin conexión; no cachea informes.
- Figuras como miniaturas que se amplían al tocarlas.
- Sin dependencias de terceros en el navegador: htmx copiado en `static/` con su versión anotada.

## 4. Seguridad

- Escucha solo en `127.0.0.1:{web.port}`. El acceso remoto lo da `tailscale serve` (ver `OPERATIONS.md`).
- Si la petición trae la cabecera de identidad de Tailscale (`Tailscale-User-Login`), debe coincidir con `web.allowed_tailscale_login`; si no coincide, 403. Verificar en la fase 0 que `tailscale serve` añade esa cabecera en la versión instalada.
- Formularios con token CSRF (doble envío: cookie `SameSite=Strict` + campo oculto).
- Cabeceras: `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- Plantillas Jinja2 con autoescape; Markdown con `markdown-it-py` (HTML desactivado) y `nh3`.
- Los SVG de los proyectos nunca se sirven: solo sus PNG rasterizados.
- El proceso web no ejecuta trabajos: inserta filas en `job` y responde. El worker los ejecuta con el mismo bloqueo que los temporizadores.
- Rutas de archivos servidas solo desde `data_dir/reports/` por ID, nunca por ruta recibida del cliente.

## 5. Respaldo en Obsidian

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
