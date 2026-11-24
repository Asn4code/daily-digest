# Reparar afirmaciones rechazadas sin rehacer la fuente

Estado: implementada, endurecida con guardia determinista anti-evasión (`B1`) y
prompts `source` v14 / `grounding` v10, y revalidada técnicamente en `WA-05`
(`docs/reviews/scoped-source-repairs.md`); tras una primera candidata real rechazada
por supresión de cifras (`source-only-d1e7546c7fce45dabc4a92e0be2c4697.json`), la
nueva candidata real (`build/phase3-live/source-only-7c83984d37c545619052ecb398f0688b.json`)
fue **aprobada científicamente** en auditoría independiente sobre esa unidad
(`D-071`, `docs/reviews/phase-3.md`), pendiente informe completo/entrega por correo
y firma humana de fase. Complementa la reparación acotada de `SourceFindings` dentro
de la validación de fase 3.

## Conversaciones cercanas al límite (2026-11-24)

Si la reparación habitual cabe, conserva exactamente su representación anterior.
Si excede el presupuesto, puede usarse una representación compacta únicamente
cuando el prefijo completo coincide con el render original del mismo paquete
Source. Se minifica el JSON y se conservan `&`, `<` y `>` escapados en el texto;
los atributos mantienen también el escape de comillas. Todos los valores del
contexto y de las evidencias permanecen idénticos al decodificar.

El contexto alternativo `source_claim_repair_compact_v1` reúne por ID la
afirmación original saneada, sus incidencias y `preserve_numbers`; los nombres
repetidos de reglas se factoran con alias cerrados y reversibles. El esquema de
salida, la reconstrucción, la conservación numérica y la validación completa no
cambian. La conversación final se vuelve a medir: si todavía no cabe, continúa
el respaldo o el estado pendiente, sin recortar fuentes ni ampliar límites.

La reproducción privada sin llamadas al proveedor pasa de **29 773** a **23 724**
caracteres con límite de **24 000**, comprobando equivalencia de cada bloque,
objetivo, incidencia y valor requerido. No demuestra por sí sola que el modelo
produzca una reparación válida. Los nodos válidos mantienen su clave original;
la compactación no cambia las entradas de generación ya aprobadas.

## Problema comprobado

La reparación actual vuelve a pedir una pieza completa. En el ensayo real,
una respuesta de NaN dejó cuatro campos rechazados; al repararla cambió listas,
añadió afirmaciones y generó otros cuatro errores. El respaldo agotó varias
peticiones sin completar la fuente. Repetir instrucciones generales no impide
que una reparación deshaga fragmentos que ya estaban respaldados.

Las respuestas privadas originales se conservan, sin copiar sus datos
científicos al repositorio público:

| Respuesta | Artefacto privado | SHA-256 |
| --- | --- | --- |
| Inicial | `build/phase3-live/diagnostics/539dc2f192124b53b2445a21910cc8ee.json` | `4642800ba5189a7f539dbacc07eb66f0dc8c68adb7aab2e132d429ae02ed7839` |
| Reparación completa | `build/phase3-live/diagnostics/cc8b98cbb0454eb2964234cbf0134cc5.json` | `1efd2e7a64a71703c5330418e814cf51d57d9e8321fac888968df681cfe8e686` |

La segunda respuesta cambia el número de interpretaciones, controles y límites.
No se pueden mezclar listas por sus índices: sus elementos se han reformulado
y reordenado. Ambas candidatas siguen rechazadas. Este diagnóstico no aprueba
una combinación de sus textos.

## Cambio propuesto

Solo para una SourceFindings con esquema correcto y errores localizables en
afirmaciones, el código fija los objetivos de reparación antes de llamar al
modelo. Cada objetivo corresponde a una afirmación completa: texto, referencias
y, cuando proceda, confianza. No se reparan por separado una cifra y sus citas.

1. El código agrupa las incidencias existentes por afirmación y asigna IDs
   cerrados, ligados a rutas y huella de la candidata original. Mantiene el
   máximo vigente de incidencias; no inventa IDs de evidencia.
2. La única petición de reparación al mismo proveedor exige un objeto con esos
   IDs exactos y el esquema correcto para cada afirmación. El modelo no elige
   rutas ni puede añadir, borrar o reordenar otras afirmaciones.
3. El código sustituye exclusivamente esos objetivos en una copia de la
   candidata original. Referencias, orden y contenido de las demás afirmaciones
   permanecen idénticos. Una respuesta fuera de ámbito se rechaza; no se mezcla
   a ciegas otra pieza completa ni se publican parches parciales.
4. La pieza reconstruida pasa de nuevo el esquema y el validador completo.
   Después conserva el cotejo semántico completo obligatorio. Que una afirmación
   no tuviera errores numéricos no significa que esté científicamente aprobada.
5. Se registran versiones y procedencia de generación/reparación mediante los
   mecanismos existentes. La caché solo guarda la pieza completa válida bajo
   su contrato; un parche no se confunde con SourceFindings. Las piezas válidas
   anteriores siguen sujetas a revalidación y cotejo.

La primera implementación se limita a la reparación de afirmaciones de fuente.
Las salidas con esquema inválido, incidencias globales o rutas que no permiten
identificar una afirmación conservan su tratamiento actual. La reparación por
cotejo negativo y las otras etapas no cambian en esta tarea.

## Límites que se conservan

- Mismo máximo de llamadas, reparación por proveedor, respaldo y tiempo de
  generación. El parche sustituye una petición existente; no añade rondas.
- Mismo presupuesto de conversación completa, incluidos contexto, candidata y
  reparación; si no cabe, se conserva el respaldo o pendiente actual. Sin podar
  fuentes, condiciones o resultados ni aumentar límites.
- Mismo inventario, privacidad y selección congelada. Ninguna nueva lectura o
  ejecución de proyectos ni acceso a destinatarios o secretos por el modelo.
- Validador completo, cotejo y bloqueo de publicación intactos. El código no
  corrige cifras, decide hechos, cierra estados humanos ni combina texto humano.
- Sin dependencias, DDL ni cambios de formato de Obsidian o Drive. Los parches
  son un contrato interno del LLM; el informe conserva su estructura existente.

## Aceptación comprobable

- Reproducción sintética donde una reparación completa corrige un error e
  introduce otro en una afirmación antes válida. La reparación acotada cambia
  solo el objetivo y conserva las demás afirmaciones exactamente.
- Dos errores en una afirmación producen un solo objetivo; varias afirmaciones
  se reparan juntas sin alterar índices o longitud de listas.
- Rechazo de IDs ajenos, objetivos omitidos/duplicados, tipos incorrectos,
  cambios de resultado, referencias inventadas y anotaciones/unidades nuevas.
- Las incidencias globales o de esquema conservan su ruta actual; las restantes
  etapas mantienen su comportamiento. No crece el número de llamadas.
- Un parche válido por esquema pero falso por cifras/referencias sigue
  pendiente. Un cotejo negativo posterior bloquea la fuente y el informe.
- Pruebas de presupuesto, privacidad, secretos, reanudación y caché; originales
  y estados humanos intactos. `make check`, puerta 3 y revisión independiente.
- Ensayo de la misma fuente real, con datos/modelos congelados, sin entrega.
  La eficacia y fidelidad se juzgan sobre otra candidata exacta, no sobre las
  dos respuestas rechazadas ni solo sobre dobles sintéticos.
