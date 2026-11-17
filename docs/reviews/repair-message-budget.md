# Revisión independiente del presupuesto de reparaciones

reviewer: codex, sesión independiente (`review_watchlist_hierarchy`)
date: 2026-11-17
scope: delta posterior a `b95c724`; router, construcción de informes, ampliaciones y contraste humano

Esta revisión no firma la puerta de fase ni aprueba un informe real pendiente.

## Hallazgos y alcance

No quedan hallazgos bloqueantes o importantes abiertos en el control de envíos
revisado. Las seis llamadas de producción al router pasan ahora el presupuesto
ya calculado por su responsable: generación y cotejo del builder, ampliación y
su cotejo, contraste humano y su cotejo. No se elevan los límites de mensajes,
esquemas, intentos o tiempo.

El router mide con `json.dumps(..., ensure_ascii=False)` la conversación completa
antes de cada llamada a `Client.complete`, incluidas las instrucciones añadidas
para reparar. Si no cabe, omite ese envío y el siguiente proveedor elegible
recibe los mensajes originales íntegros. No reduce fuentes ni conserva las
instrucciones de reparación del proveedor anterior. Si una reparación sí cabe,
puede continuar en el mismo proveedor dentro de los intentos existentes.

**Limitación de diagnóstico documentada:** las reglas
`message_budget_exceeded` y `repair_message_budget_exceeded` se registran en
`Router.issues`. El builder puede persistir `grounding_unavailable` y las
ampliaciones o revisiones una indisponibilidad genérica, sin el motivo específico
de presupuesto. Esto ya ocurría con otras causas de indisponibilidad; la nueva
documentación de LLM y D-067 delimita la promesa al registro del router. No se
afirma trazabilidad específica de ese motivo hasta la interfaz o el artefacto
persistido.

## Comprobaciones independientes

- **45 pruebas pasan:** router, caché de nodos, fuentes extensas, grounding y
  cinco pruebas privadas. El recorrido de fuentes conserva los treinta elementos
  del inventario, los controles y el estado humano; sus peticiones, incluidas
  reparaciones, respetan los 24 000 caracteres. Incluye las tres regresiones que
  aparecieron al aumentar el prompt `source` a v10.
- Las privadas prueban JSON inválido y rechazo de validación, ausencia de una
  salida válida en todos los proveedores, privacidad, Unicode y frontera exacta
  del presupuesto. Cuando no cabe ninguna reparación, solo se envía una vez el
  original a cada proveedor permitido. En ámbito privado nunca se usa el externo.
  Una reparación con espacio suficiente conserva fuentes y proveedor. Se
  comprueban los mensajes reales del transporte HTTP simulado.
- **43 pruebas E2E pasan:** ampliaciones y revisión activa, con los cuatro
  argumentos adicionales de presupuesto. Se mantienen validación y cotejo antes
  de publicar y los estados humanos no cambian por este control.
- Inspección de firma opcional, llamadas, privacidad y caché. El control no cambia
  las claves ni la revalidación o elegibilidad de nodos válidos; una reutilización
  sin HTTP no requiere gastar presupuesto de envío. El builder y los otros
  responsables conservan además sus comprobaciones previas del paquete original.
  Los presupuestos de mensajes y JSON Schema siguen siendo independientes.

Comandos reproducibles:

```bash
PYTHONPATH=. .venv/bin/pytest -q --import-mode=importlib build/review-wa11/test_repair_budget.py tests/unit/test_llm_router.py tests/unit/test_node_cache.py tests/integration/test_source_pipeline.py tests/integration/test_grounding.py
.venv/bin/pytest -q tests/e2e/test_active_review.py tests/e2e/test_followups.py
```

## Veredicto

**Aprobada técnicamente**, con 88 pruebas focalizadas que pasan (83 compartidas
y cinco privadas), para el alcance de código indicado. No se modificaron
producción, pruebas compartidas, commits o firmas desde esta sesión y no se
utilizaron proveedores reales. La suite completa, la puerta automática y la
validación humana y del informe real mantienen sus comprobaciones propias.
