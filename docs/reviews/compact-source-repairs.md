# Revisión independiente de reparación compacta de fuentes

reviewer: codex, sesión independiente (`review_watchlist_hierarchy`)
date: 2026-11-24
scope: delta de `prompts.py`, `source_repair.py` y `router.py` sobre `3d0fa9e`

**Aprobación técnica del delta revisado**, sin hallazgos de seguridad o integridad
abiertos. No aprueba la muestra real, la capacidad del proveedor, la fase ni una
firma humana. El cambio independiente de `grounding_watchlist` queda fuera de
esta revisión.

## Contrato comprobado

La alternativa solo se intenta para una reparación acotada de SourceFindings
cuando la conversación habitual excede el presupuesto existente. Reconstruye
los dos mensajes originales desde el paquete saneado y exige igualdad completa:
mensajes añadidos, roles cambiados, contenido diferente o un paquete distinto
impiden sustituir el prefijo. El mensaje de sistema permanece intacto.

La minificación cambia la representación JSON, no sus valores. Los bloques
conservan la proyección original del contexto y evidencias, incluso en modo de
referencias. El contenido mantiene escapados `&`, `<` y `>`; los atributos siguen
escapando comillas. Comprobé ida y vuelta con entidades literales, delimitadores
inyectados, comillas, Unicode, controles representados en JSON y espacios dentro
de strings. No se mutan paquetes ni mensajes originales.

El contexto de reparación conserva cada objetivo por su ID original, la
afirmación completa con el mismo saneado HTML anterior, sus errores y campos,
y `preserve_numbers`. Los alias tienen una tabla cerrada de reglas y no cambian
la asociación de errores. La aridad, confidence y referencias siguen gobernadas
por el mismo esquema SourceClaimRepair. Las instrucciones repetidas se factorizan;
no se atribuye identidad byte a los dos prompts de reparación.

La aplicación del parche, sustitución exclusiva de objetivos, validación de la
pieza completa y cotejo posterior no cambian. El presupuesto se vuelve a medir
antes de Client.complete, incluyendo todos los mensajes alternativos. Si aún
excede el límite no se envía. No aumentan límites, llamadas ni plazos. La generación
normal, reparaciones que ya cabían y claves de caché de piezas válidas mantienen
su entrada original; las restricciones de proveedor siguen aplicándose antes
de elegir la conversación.

## Pruebas y observación de integración

Pasaron **82 pruebas focalizadas**: 66 compartidas y 16 privadas. Las privadas
incluyen equivalencia de bloques, vinculación exacta, HTML saneado, varios errores
y objetivos, modos de representación y reparaciones todavía inválidas.

```bash
PYTHONPATH=. .venv/bin/pytest -q --import-mode=importlib build/review-compact-repairs/test_compaction_review.py tests/unit/test_compact_source_repair.py tests/unit/test_scoped_source_repairs.py tests/unit/test_llm_router.py tests/integration/test_grounding.py tests/integration/test_source_pipeline.py
```

La primera ejecución adicional de `test_source_pipeline.py` encontró tres
expectativas obsoletas en el caso de fuentes extensas. Su doble corrompía solo
SourceFindings, devolvía SourceClaimRepair válido y exigía que no pudiera llamarse
ese esquema: antes el presupuesto impedía la reparación; ahora puede caber y
terminar correctamente. Se comunicó al constructor para actualizar el escenario,
sin modificar pruebas compartidas desde esta revisión. Al inyectar también en el
parche la cifra inventada, referencia ajena o referencia decorada, las tres
reproducciones privadas conservan la extracción pendiente, omiten su sección y
`require_complete` rechaza el informe. El constructor corrigió el doble compartido
para corromper también los parches y exigir que se intente repararlos; la ejecución
final indicada incluye esos tres negativos corregidos y pasa.

También ejecuté el diagnóstico retenido, sin llamadas:
`build/phase3-live/check_compact_probe.py`. Reproduce **29.773 → 23.724 caracteres**
frente al mismo límite de 24.000, con 12 objetivos y equivalencia exacta de bloques,
afirmaciones saneadas, errores y cifras que deben conservarse. No se sustituyen ni
resumen las evidencias para obtener ese tamaño.

No se hicieron llamadas a proveedores reales ni se publicaron datos científicos
del diagnóstico privado. La reducción de tamaño permite intentar una reparación;
no acredita que un proveedor vaya a producir una pieza válida o fiel.
