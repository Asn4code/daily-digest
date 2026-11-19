# Revisión independiente: decisiones y alcance de requisitos

reviewer: codex, sesión independiente (`review_watchlist`)
date: 2026-11-19
verdict: mitigación técnica pertinente; eficacia real pendiente

## Candidata rechazada

Artefacto privado
`build/phase3-live/diagnostics/c138eed79a384770adb90611fe9c6773.json`,
SHA-256 `e6d02421e6161b2e97ceb9bb5f76fb3398121c37c28551b6dcc5fb4209ad49f3`.
La revisión se limita a esa pieza `SourceFindings`, no a un informe completo.
Su ventana histórica es el 9 de noviembre de 2026, 05:00–16:00 UTC; no describe
el estado actual.

**SF1 permanece rechazado.** La candidata convierte la decisión humana de si
aceptar cambios de protocolo en una aceptación obligatoria para toda recuperación.
También homogeneiza causas y vías distintas. Una condición de regeneración no
se aplica por defecto a localizar resultados existentes o entregar un paquete.
Que otro campo conserve la decisión pendiente no corrige el requisito categórico.

El cotejo automático había aprobado la candidata; la revisión independiente la
rechazó. El detalle exacto, con datos de los proyectos, permanece fuera del
repositorio público en
`build/review-watchlist-real/review-source-c138eed79a384770adb90611fe9c6773.json`,
SHA-256 `346daa33a1ab57b7e8993e2b291d7b77f15289cb6b300a7df6ac3654c54a56f3`.

## Mitigación revisada

Se revisó el cambio de `source` v10 a v11 y de `grounding` v7 a v8. Las nuevas
instrucciones vinculan cada requisito con su acción y subconjunto; impiden
atribuir una causa única a faltantes con causas diferentes; y conservan la
elección de si aceptar cambios sin presentarlos como obligatorios o autorizados.
El cotejo exige comprobar esas distinciones también en `controls`, `limitations`
e `interpretations`, y rechazar una contradicción aunque exista una cautela
correcta en otro campo. Mantiene la posibilidad de expresar una condición clara
sin repetirla mecánicamente.

La mitigación aborda SF1 sin modificar el contrato, rebajar validadores ni
introducir decisiones humanas automáticas. No se identifican contradicciones
con las instrucciones previas de procedencia, estados y propuestas.

## Pruebas y límites

Ejecución independiente de
`.venv/bin/python -m pytest -q tests/integration/test_watchlist_fidelity.py`:
**8 pruebas pasan**. Los casos nuevos introducen el requisito indebido en los
campos indicados y comprueban tanto el bloqueo de la pieza y sus descendientes
como la reparación antes de completar el informe. Conservan el texto de la
fuente y el estado humano. Ruff y formato del archivo de pruebas también pasan.

El transporte es un doble determinista que devuelve explícitamente el rechazo
semántico. Demuestra la orquestación del cotejo y la reparación; no demuestra
que un proveedor real detecte SF1, ni que preserve todas las causas y condiciones
en una nueva salida.

## Veredicto limitado

**Mitigación técnica pertinente para una nueva validación.** La candidata con
la huella anterior continúa rechazada e inmutable. La eficacia real requiere
otra candidata exacta y un nuevo cotejo independiente; esta ficha no aprueba el
ensayo, el informe completo, la fase ni ninguna comprensión humana. No se
modifican firmas ni se autoriza una entrega.

## Compactación de `source` v11

Se cotejó el texto compacto definitivo contra `source` v10 de HEAD y la
mitigación SF1 previamente revisada. Archivo revisado:
`src/digest/llm/prompts/source.md`, SHA-256
`ff99ca09b91acd561ea4706a98b4d6a2a19ea6e0192e892341d5866c8d467c10`.
Contiene 3652 caracteres frente a los 3816 de la versión anterior; conserva la
corrección SF1 sin aumentar límites ni recortar evidencias.

Durante el cotejo se restituyeron las formulaciones explícitas de respaldo de
las afirmaciones, clasificación del histórico descubierto después, prohibición
de inferir patrones desde la existencia de figuras, transcripción de listas
calculadas y marcadores de fichero entre ángulos. También se conservó que solo
una nota **posterior** que documenta la resolución puede dejar sin vigencia una
limitación antigua: una nota anterior no anula un problema posterior.

El texto definitivo mantiene los controles del contrato y los matices numéricos,
temporales, de procedencia y de estados humanos, junto con la decisión y el
alcance de SF1. No se identifican controles materiales perdidos en la
compactación. Esta es una revisión de equivalencia de instrucciones; no prueba
su eficacia en una salida real. Las comprobaciones automáticas finales y la
puerta se ejecutan sobre el estado cerrado por el constructor. La candidata
anterior continúa rechazada y no se aprueban informe, fase ni entrega.
