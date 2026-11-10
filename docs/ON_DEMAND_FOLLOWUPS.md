# Ampliaciones y comprobaciones a petición

Diseño para la fase 3, solicitado por la persona durante la validación del diario
(D-050). Todavía no implementado. No sustituye la firma pendiente de fase 2.

## Recorrido

Al final del correo, del informe web y de la vista para la vault aparece
«¿Quieres ampliar o comprobar algo?» con un enlace a la webapp. El enlace conserva
el ID y la revisión exactos del informe, también si ya existe otro más reciente.
No se ejecuta ninguna acción al abrir un enlace del correo.

La persona señala una o varias frases, escribe su duda y elige:

- **Explicar mejor:** desarrollar el significado, los conceptos y las consecuencias
  con las evidencias que sustentan las frases. Un ejemplo hipotético se identifica
  como tal y no se presenta como un resultado del proyecto.
- **Comprobar una afirmación:** contrastar la declaración con sus evidencias y,
  cuando exista una comprobación implementada, con datos disponibles de solo lectura.

Un único envío del formulario crea la solicitud. No hay comprobaciones científicas
automáticas por leer el diario. La pantalla muestra el progreso del trabajo y el
resultado; el worker hace la generación y las comprobaciones, nunca el proceso web.

Al terminar, llega **un informe de ampliación por correo**, con enlace al original.
Se conserva y copia por los canales configurados, sin sobrescribir el diario ni
respuestas humanas. El original mantiene todos los resultados del intervalo; la
ampliación identifica expresamente las frases solicitadas y su cobertura parcial.
No reserva ni cierra otro intervalo diario, ni modifica el horario del servicio.

La ampliación procesa solo las frases, fuentes y nodos necesarios para la
solicitud. Aclarar una gráfica de VCD no obliga a regenerar Benchmark. Los nodos
ajenos que se reutilicen conservan su versión de prompt, modelo, contexto y cotejo
efectivos; nunca se presentan como regenerados con el modelo o prompt nuevos.

## Qué cuenta como comprobación

Releer una nota permite confirmar qué declaró su autor, pero no verifica por sí
solo el experimento. La ampliación separa declaración original, aclaración,
comprobación efectivamente realizada y conclusión que esta permite sostener.

El código controla un catálogo explícito de comprobaciones: lectura acotada de
archivos, inventarios y cálculos implementados por el servicio sobre datos ya
existentes. El modelo no elige rutas ni comandos. Cada comprobación ejecutada
registra datos utilizados, sus hashes/IDs de evidencia, fecha, método o versión,
resultado y limitaciones. Los datos que han cambiado se capturan como evidencia
nueva; no alteran el paquete histórico que respaldaba el informe original.

Ejemplo: auditar las puntuaciones almacenadas y recalcular una correlación con
un método implementado puede comprobar el valor registrado. No acredita por sí
solo calidad predictiva. Si faltan datos, se explica qué falta y queda no verificable;
eso no demuestra que la afirmación sea falsa.

La solicitud no autoriza a ejecutar scripts o notebooks del proyecto, lanzar MD
o predicciones nuevas ni escribir en sus raíces. Si la respuesta necesita una
ejecución que el servicio no realiza, se identifica esa necesidad como pendiente
externa. No se presenta una propuesta de análisis como una comprobación realizada.

## Contenido de la ampliación

1. Informe y revisión de origen, frases seleccionadas y pregunta de la persona.
2. Explicación ampliada con referencias; ejemplos separados de hechos observados.
3. Qué se comprobó, con qué datos y método, y qué no se pudo comprobar.
4. Resultado: respaldado en el alcance indicado, discrepancia que investigar o
   no verificable con los datos disponibles; incertidumbre y límites decisivos.
5. Consecuencia para la interpretación o el próximo foco, como propuesta sin
   cambiar comprensión, aceptación o planes humanos.

Un resultado legítimo «no verificable» necesita un motivo documentado. Un timeout,
una salida LLM inválida o una pieza requerida fallida deja el trabajo pendiente;
no permite enviar un informe final con sustituciones mecánicas (D-047).

## Contrato de seguridad y persistencia

Las frases se resuelven contra campos existentes del informe inmutable mediante
ID de informe, revisión y referencia interna validada. Nunca se aceptan rutas de
archivos, comandos o destinatarios desde la pregunta. El acceso exige la identidad
autorizada, CSRF y los mismos controles de archivos que el resto de la webapp.

El texto de la pregunta y sus selecciones son datos no confiables, acotados y
saneados. La política de privacidad hereda todos los proyectos y contexto humano
implicados; una pregunta no permite enviar al proveedor externo contenido privado.
Los paquetes tienen presupuesto y las respuestas pasan esquemas, referencias,
cifras/unidades, procedencia y cotejo de fidelidad antes de publicar.

Las solicitudes y sus resultados conservan linaje independiente. Un doble envío
del mismo formulario no duplica trabajo ni correo. Cada ampliación tiene identidad
de informe propia y Message-ID estable para sus reintentos; una entrega incierta
no se reintenta sola. No se reutiliza la identidad del correo diario original.

Antes de implementar se concretarán el tipo de trabajo, su persistencia y los
artefactos versionados. No se modifica ahora el esquema SQLite publicado ni los
formatos de Obsidian/Drive. Si hace falta una migración o cambiar esos formatos,
se presentará antes de implementarla, según AGENTS.md.

## Aceptación de WA-08

- Desde el final del correo móvil se solicita una aclaración de una frase de una
  revisión anterior, aunque exista otro diario más reciente; llega una ampliación
  vinculada a aquella revisión y el original conserva sus hashes.
- Una comprobación real sobre datos sintéticos distingue resultado reproducido,
  discrepancia y falta de datos. Un texto del modelo que solo repite la nota no
  se etiqueta como verificación del cálculo.
- El servidor web solo encola; el worker conserva los estados y texto humanos.
- Una solicitud duplicada produce un único trabajo y una única entrega lógica.
- Pedir una explicación sobre un proyecto no vuelve a generar otro sin cambios;
  la reutilización comprueba paquete, políticas, contratos y certificados, y
  conserva las versiones efectivas de cada pieza.
- IDs o campos ajenos, acceso no autorizado, ausencia de CSRF, rutas maliciosas
  e instrucciones en preguntas o proyectos no amplían el ámbito permitido.
- Un proyecto privado no llega al proveedor externo; las credenciales no aparecen
  en preguntas almacenadas, paquetes, logs o respuestas.
- Una pieza requerida inválida impide la entrega final. Los reintentos reutilizan
  nodos válidos y respetan el estado incierto del correo.
- Pruebas con dobles LLM, SMTP y Drive, sin llamar a proveedores reales ni ejecutar
  contenido de los proyectos.
