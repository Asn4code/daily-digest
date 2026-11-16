# Seguimiento con contexto inicial grande

WA-11, aprobada por la persona en el tablero y el chat el 2026-11-16.
Implementación en curso tras el hallazgo de la validación real de WA-05.

## Problema observado

Los dos temas humanos se guardan correctamente. El primer avance del perfil de
validación incorpora 2649 evidencias y sesenta resultados de referencia histórica,
sin resultados clasificados como actividad del día. Las fuentes tienen cobertura
parcial. Enviar todas las evidencias del proyecto dentro de cada pregunta supera
los 64 000 caracteres del paquete de seguimiento. El trabajo queda pendiente
antes de llamar a los modelos; no publica, entrega ni cierra un intervalo.

El borrador se conserva como `rep_preview_2026-11-16_r1`, trabajo 1 del perfil
temporal. Estos recuentos describen el tamaño del problema técnico, no avance
científico. El bloqueo no se resuelve aumentando el límite, omitiendo controles,
ignorando la cobertura o sustituyendo la evaluación por texto mecánico.

## Cambio propuesto

Separar tres responsabilidades ya presentes en el diseño jerárquico:

1. **Inventario completo.** Conservar todos los resultados y evidencias del
   intervalo, su procedencia y cobertura. Distinguir contexto inicial o histórico
   de hechos actuales; una pregunta humana no cambia esa clasificación.
2. **Contexto de seguimiento.** Preparar piezas acotadas de fuentes coherentes,
   conservando observación, interpretación, controles y límites. Reutilizar las
   piezas ya validadas y su caché, en lugar de enviar todo el histórico una vez
   por pregunta. Lo que falte del contexto inicial queda identificado; no se
   presenta como analizado ni como ausencia de novedades.
3. **Evaluación por pregunta.** Construir un paquete derivado de esas piezas,
   con referencias verificables y manifiesto de dependencias. Si no cabe en un
   nivel, reducir jerárquicamente mediante piezas validadas, con la cobertura
   necesaria para saber qué se revisó. No recortar frases ni elegir rutas con
   el modelo. La síntesis no convierte un inventario incompleto en una conclusión
   general ni permite `no_new` sin base comparable y cobertura suficiente.

Cada nivel mantiene los límites actuales y el cotejo antes de publicar. Los
reintentos conservan las preguntas fijadas y reutilizan solo piezas válidas.
El tiempo máximo de generación continúa vigente; una pieza que no pueda
terminarse queda pendiente, con el motivo y trabajo conservados.

El diario sigue orientado a la actividad del intervalo; el semanal conserva su
etapa crítica. La preparación inicial no transforma automáticamente todo el
histórico en trabajo del día ni exige releerlo entero cada noche.

## Alcance que no cambia

Se conservan la interfaz de preguntas, prioridades y estados humanos, las raíces
y fuentes permitidas, la privacidad ancestral, SQLite y los formatos aprobados
de la sección «Seguimiento solicitado» en Obsidian/Drive. No se ejecutan análisis
ni se configura una fuente nueva para completar una respuesta. Si el seguimiento
requiere métricas no declaradas, se explica qué falta.

La generación sin actividad y con cobertura fallida continúa respetando el
contrato actual: no se declara ausencia de trabajo ni se aprueba la captura.
Cambiar ese contrato exigiría una decisión separada, fuera de esta propuesta.

## Criterios de aceptación

- Regresión sintética de una captura inicial de al menos 2600 evidencias:
  paquetes acotados, inventario íntegro y preguntas fijadas; ninguna afirmación
  respaldada solo por metadatos de volumen o por texto humano.
- Caso completo con fuentes permitidas y cobertura suficiente: ambos temas
  pueden evaluarse sin introducir todas las evidencias originales en cada llamada.
- Controles separados de la observación, fuentes contradictorias, histórico sin
  novedades y fuente ausente: no se pierden límites ni se fabrica comparabilidad.
- Un nodo pendiente bloquea sus descendientes; reanudar reutiliza los válidos.
  Privacidad de todos los padres conservada, incluso con proyectos retirados.
- Comparar con el borrador real conservado, sin entregar hasta validar, y revisar
  el resultado con una sesión independiente. `make check`, puerta automática y
  comprobación humana de móvil/detalle; no se rebajan gates ni validadores.

## Recorrido implementado

El camino directo permanece para preguntas cuyo paquete íntegro cabe. Cuando
no cabe, `monitoring_tree` prepara un árbol específico de seguimiento. Calcula
primero las unidades coherentes a nivel de proyecto, con enlaces entre archivos,
comparaciones y controles, antes de cualquier reparto por resultado. El contexto
de notas de una tarea acompaña a sus unidades; varias unidades completas pueden
compartir paquete. Una unidad indivisible que exceda el límite queda pendiente.

Una fuente `source:*` ya cotejada se reutiliza únicamente si es compatible con
la unidad completa y sus controles. Reutilizar una observación no elimina la
necesidad de leer un control posterior: en ese caso se prepara la unidad entera.
Las hojas nuevas son `watchctx:<ficha>:source:<hash>`; las reducciones usan
`watchctx:<ficha>:reduce:<nivel>:<hash>`. La raíz conserva `watch:<ficha>` y el
contrato de evaluación y los formatos humanos de WA-10.

`MonitoringContext` contiene observaciones, interpretaciones, controles, límites
y preguntas, con un máximo de catorce afirmaciones breves: 600 caracteres y ocho
referencias por afirmación. No declara estado humano ni ausencia global de
novedades. Cada hoja y reducción exige esquema, validador y cotejo propios.
Hasta ocho niveles de reducción, mensajes de hasta 64 000 caracteres o el límite
configurado menor, esquemas de hasta 32 000 y cotejos de hasta 128 000, siempre
respetando también el límite configurado. No se elevan los topes previos.

Los paquetes derivados contienen las piezas de padres exactas y referencias a
sus evidencias originales. El cotejo comprueba la fidelidad a esos padres: puede
citar una frase literal de una afirmación del padre junto con sus IDs originales.
Eso no autoriza citar preguntas humanas, metadatos o prosa arbitraria como prueba.
Las hojas se cotejan contra los originales completos; no se reenvía todo el
histórico en cada nivel. El manifiesto, contrastado de nuevo al publicar,
comprueba cobertura íntegra, unidad coherente, padres exactos, privacidad,
ausencia de ciclos y pertenencia de cada nodo. Una pieza pendiente bloquea
sus descendientes y sigue requerida para completar el informe.

`human_context.monitoring_inventory` fija las entradas preparadas antes de añadir
historia. `human_context.watch_trees` registra por pregunta su revisión, entradas,
hojas, padres y raíz. Sus entradas deben coincidir exactamente con el inventario
preparado del ámbito y la historia de esa pregunta, incluido contexto auxiliar.
Esos metadatos de control no se envían al plan como contexto científico. Las
preguntas y el inventario privado del trabajo siguen fijados al reanudar.

Las evidencias se serializan y sanea su contenido, claves y metadatos una sola vez
por generación antes de reutilizarlas al medir paquetes. La caché continúa
identificando entradas exactas, modelos, prompts y validadores, e incluye el
contrato y verificador de seguimiento. Cambiar una pieza invalida sus derivados;
no borra los artefactos anteriores ni sustituye texto humano.
