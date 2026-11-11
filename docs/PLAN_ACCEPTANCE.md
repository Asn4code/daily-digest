# Decisión humana sobre el próximo foco (WA-03)

Diseño de implementación. El esquema SQLite existente no cambia. La persona
aprobó expresamente este formato de exportación el 2026-11-11, en respuesta a
la consulta requerida por `AGENTS.md`.

## Pantalla y persistencia

Cada informe conserva su propuesta original. La pantalla Plan muestra acción,
criterio de finalización, dependencias, motivo de prioridad, objetivo, dudas y
enlaces a las evidencias. Permite guardar un ajuste, aceptar o descartar cada
elemento. Guardar un ajuste no lo acepta. Elegir una misión distinta sustituye
el foco activo solo por esa acción expresa; el historial conserva las decisiones
anteriores. Una evidencia nueva puede justificar otra propuesta, no cambiar el
foco activo. Un formulario obsoleto debe recargarse antes de decidir.

`plan_item.edited_text` guarda la acción ajustada por la persona; los campos
generados no se cambian. `meta` conserva ajustes de criterio/dependencia,
decisiones e instantáneas inmutables con ID aleatorio. `accepted` representa la
selección vigente, con una misión como máximo y hasta dos calentamientos. Las
instantáneas mantienen las decisiones y el texto anteriores.

La petición web solo guarda y encola. El worker exporta la instantánea exacta,
incluso si la persona cambia su foco antes de que se procese la cola. La siguiente
generación recibe la selección humana vigente y sus ajustes; no marca resultados
como comprendidos ni cambia Kanvas. Las dudas y el contraste semanal se muestran
con su procedencia; no se convierten mecánicamente en tareas aceptadas.

## Formato aprobado

Se añaden archivos, sin modificar ningún informe ni nota existente:

- Vault: `Planes/AAAA-MM-DD-<id>.md`, donde `<id>` es el identificador de una
  decisión humana. La fecha usa la zona configurada.
- Drive: `plans/<id>/plan.md` y `plans/<id>/plan.json`, con `rclone copy --immutable`.
- Datos del servicio: `plans/<id>/plan.md` y `plan.json`.

Ejemplo de nota (valores sintéticos):

```markdown
# Próximo foco · decisión del 11/11/2026

## Misión aceptada
Comparar el resultado con el control que falta.

Terminado cuando: la comparación documenta coincidencias y diferencias.
Dependencia: disponer del control.
Motivo de la propuesta: resolver la incertidumbre declarada [ev_ejemplo].
Origen: propuesta del informe rep_ejemplo_r1; ajustada por la persona.

## Calentamientos aceptados
No se han elegido calentamientos.

## Procedencia
Decisión humana: plan_<id> · hora UTC · revisión original del informe.
Las afirmaciones de la propuesta conservan sus referencias; los ajustes humanos
se identifican como texto humano y no como evidencia comprobada.
```

`plan.json` contiene versión `1`, ID y hora UTC de la decisión, informe de origen,
tipo de acción humana (`save`, `accept`, `dismiss`), elemento afectado y selección
vigente. Cada elemento conserva su ID, propuesta original, proyecto, evidencias,
acción/criterio/dependencia efectivos y procedencia humana de sus ajustes.

Cada decisión crea una instantánea distinta. Un reenvío del mismo formulario
devuelve la misma decisión y no vuelve a copiar ni a enviar correo. Se registran
por separado los intentos y resultados de Obsidian y Drive. No se borra ni se
sobrescribe ninguna exportación anterior; una entrega fallida sigue pendiente.
