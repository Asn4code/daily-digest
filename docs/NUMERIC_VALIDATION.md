# Contraste numérico: diagnóstico y propuesta

Estado: WA-12 terminada técnicamente, con revisión independiente; el ensayo real y la firma de fase siguen pendientes.

El avance retrospectivo de las dos preguntas quedó pendiente. La evaluación de
cristales tuvo generación y cotejo válidos; la de semillas agotó el tiempo tras
extracciones rechazadas y esperas del respaldo. No hubo entrega. Repetir el
informe completo sin resolver estos rechazos puede consumir otro plazo sin
producir un informe final.

## Problema reproducido

El validador actual reconoce cantidades y su siguiente palabra mediante reglas
léxicas. Algunas citas correctas se rechazan por confundir texto con unidades.
Ejemplos sintéticos, sin datos de los proyectos reales:

| Fuente citada | Afirmación | Resultado antes de WA-12 |
| --- | --- | --- |
| `Completo, 12 de 12 (1ABC_A terminó).` | La misma frase literal | Rechazada: parte del ID se interpreta como cantidad |
| ``Se registraron 3 `partial`.`` | La misma frase literal | Rechazada: el formato se elimina de forma distinta en fuente y salida |
| `Semillas 1-5 con el protocolo A.` | `Semillas 1-5 mediante el protocolo A.` | Rechazada: «mediante» se interpreta como unidad |
| `Cobertura 12 de 20 pares; 11 al incluir el control.` | `Cobertura 12 de 20 pares; 11 si se incluye el control.` | Rechazada: «si» se interpreta como unidad |
| `El lote 1 quedó archivado.` | La misma frase literal | Rechazada: «quedó» se interpreta como unidad |

Estos casos no autorizan aceptar reformulaciones distintas: «semillas 1–5» no
acredita «5 semillas», ni un total sin etiqueta acredita cualquier etiqueta de
recuento. También siguen rechazándose cifras que proceden de una evidencia
no citada y cantidades o unidades inventadas.

La propuesta anterior de eximir un ID tras un número y un paréntesis se retiró:
permitía ocultar unidades u operadores antes/después de ese paréntesis. Las
reproducciones se conservan en `reviews/structure-parentheses.md`. No se
reintroducirá esa excepción ni una aceptación global de citas entre comillas.

## Cambio propuesto

Corregir el contraste numérico mediante una representación común y conservadora
de los fragmentos de fuente y salida, en lugar de acumular excepciones de frases.
Esta representación es una vista derivada: no sustituye extractos, originales,
hashes ni las citas literales exigidas por GroundingAudit.

1. Separar formato Markdown de texto literal e identificadores. Preservar
   guiones bajos, dimensiones, signos y operaciones; no convertir una unidad en
   otra al retirar formato. Fuente y salida recorren el mismo normalizador.
2. Reconocer IDs respaldados como tokens completos, conservando el análisis de
   las cantidades y unidades adyacentes. Un paréntesis no oculta dimensiones ni
   convierte un producto o cociente en un recuento independiente.
3. Distinguir rangos, recuentos y medidas, y sus conectores en prosa. No inferir
   recuentos a partir de los extremos de un rango ni completar unidades ausentes
   a partir de otra evidencia.
4. Mantener el rechazo conservador de asociaciones ambiguas; cada campo se
   contrasta solo con sus referencias. El cotejo semántico sigue siendo
   obligatorio y no sustituye las comprobaciones deterministas.
5. Reanudar el ensayo conservando inventario, preguntas, modelos y revisiones.
   Publicar únicamente cuando todas las secciones y cotejos requeridos validen.

Sin dependencias nuevas, cambios SQLite ni cambios de formato de Obsidian/Drive.
No cambia cobertura, privacidad, límites de paquetes o reintentos, ni estados
humanos. La selección y ejecución de análisis de los proyectos quedan fuera.

## Aceptación comprobable

- Tests pytest con aserciones de aceptación/rechazo, no solo un script que
  imprime su diagnóstico.
- Regresiones sintéticas de los cinco casos y de números/etiquetas realmente
  no respaldados, incluidas referencias ajenas y rangos mal interpretados.
- Rechazo de los cinco escapes de paréntesis del intento retirado; unidades
  fuera/dentro de citas, Markdown, cocientes, productos, exponentes y signos.
  Cubrir formato alrededor de operadores y unidades partidas por énfasis,
  además de asociaciones incorrectas entre cantidades dentro de una misma fuente.
- Regresión completa de unidades simples/compuestas, identificadores Git/PDB,
  timestamps y secretos, además de límites de reparación y privacidad.
- `make check`, puerta automática de fase 3 y revisión adversarial independiente.
- Ensayo real sin entrega y cotejo de su revisión exacta; el éxito sintético no
  firma utilidad humana ni demuestra resultados científicos nuevos.

Si una solución concreta no puede satisfacer simultáneamente estos criterios,
se documenta el caso pendiente y se revisa la propuesta antes de cambiar el
contrato. No se relajan reglas para obtener un informe presentable.

## Revisión preparatoria

El 17 de noviembre, una sesión independiente (`review_watchlist_hierarchy`)
reprodujo los cinco rechazos sintéticos: tres citas literales y dos paráfrasis
que conservan rango/condición. También reejecutó cinco variantes inseguras de
paréntesis, todas rechazadas. No encontró impedimentos para proponer WA-12;
esto no aprueba una implementación ni una salida real. La aceptación exigirá
aserciones y casos adversariales, manteniendo originales y cotejo semántico.
Los rechazos numéricos reales deben examinarse individualmente: algunos son
correctos, y los timeouts constituyen otra causa independiente.

## Implementación en revisión

`digest.llm.quantities` construye una vista léxica común sin modificar originales.
Distingue formato de operaciones ambiguas, conserva guiones bajos y dimensiones,
reconoce IDs PDB íntegros y enlaza operandos, unidades y anotaciones completas.
Los rangos y relaciones necesitan respaldo conjunto en una fuente citada; sus
extremos no se reutilizan como recuentos independientes. No calcula resultados.

Las anotaciones no son una exención: se contrastan como parte de la cantidad y
se inspeccionan también sus números y unidades dentro/después. Las agrupaciones
con precedencia o símbolos matemáticos no soportados quedan pendientes. La
caché incluye el código de esta capa y revalida al reutilizar una pieza.

La revisión adversarial ha añadido casos de signos compactos, operaciones
Unicode, formato que concatena cifras, extremos ocultos tras puntos, dimensiones
entre paréntesis y anotaciones tomadas de fuentes diferentes. Las correcciones
se comprueban con pruebas de aceptación y rechazo; no aprueban por sí mismas el
informe real ni la firma humana de fase.


## Refinamiento del ensayo real (19 de noviembre)

Una cita literal de un ratio quedaba rechazada por no repetir la nota de
procedencia. Se admite el fragmento sin añadir etiquetas, dimensiones o notas
nuevas. Las notas que sí se afirman siguen vinculadas completas a su operando y
a una misma fuente; notas ambiguas o dimensionales no se pueden omitir. El otro
intento que añadía una etiqueta de recuento sin respaldo continúa rechazado.

La revisión adicional de `reviews/annotation-omission.md` conserva los negativos
ASCII/Unicode, calificadores dimensionales y sintaxis malformada. No acepta el
informe real ni sustituye controles científicos o firmas humanas.
