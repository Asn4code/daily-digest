---
phase: 0
builder: codex-builder
reviewer: codex-independent-session
verdict: aprobada
date: 2026-11-04
---

# Revisión de la fase 0: Contratos y base

Protocolo en docs/VALIDATION.md. El revisor rellena «Hallazgos» y «Veredicto»; la persona rellena «Firma».

## Informe automático

Informe: [comprobación automática](../../build/gates/phase-0.md), resultado PROVISIONAL.

Validación de servicios reales completada mediante `digest --config config.yaml doctor` con CREDENTIALS_DIRECTORY; retorno 0. Configuración privada excluida de Git.
(resultado de `python scripts/phase_gate.py 0 --no-manual`).

## Hallazgos

- [x] **bloqueante resuelto — fuga de claves dinámicas en errores de configuración.** `src/digest/config.py:254`: añadir a `llm.providers` la entrada `FAKE_SECRET_MAPPING_KEY: {timeout_s: bad}` y ejecutar doctor imprimía el nombre arbitrario en cada error de validación, vulnerando la redacción de secretos. El constructor corrigió la ubicación en `src/digest/config.py:257` (commit `4ff2e61`); regresión de carga directa y CLI en `tests/unit/test_config.py:107`. La prueba independiente `test_dynamic_mapping_key_is_redacted` falló antes y pasa después. No quedan bloqueantes abiertos.
- [ ] **menor — preguntas de contratos con estado documental desactualizado.** `docs/DECISIONS.md:39`, `:44` y `:45`: Q-01/Q-06/Q-07 siguen abiertas mientras los hallazgos finales de CB-06 describen servicios comprobados. Reproducción: comparar «Preguntas abiertas» con «Cierre CB-06». Antes de la firma, la persona debe confirmar las respuestas y distinguir los límites aún no medidos; no se deben publicar rutas o credenciales privadas para resolverlo. Comprobación documental, sin test de código.

### Comprobaciones y alcance

Lectura de AGENTS.md, SPEC, ARCHITECTURE, OPERATIONS, TESTING, VALIDATION, ROADMAP y DECISIONS. Revisión limitada a contratos y base; captura, publicación y webapp siguen fuera de esta fase. No se abrieron `config.yaml`, claves reales ni transcripciones, ni se ejecutaron proyectos reales.

- Puerta inicial y tras la corrección: `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/phase_gate.py 0 --no-manual`, retorno **3 PROVISIONAL**, informe enlazado arriba. Sin reglas incumplidas ni escenarios omitidos; `doctor-host` y firma se omiten conforme a ese modo.
- `PATH="$PWD/.venv/bin:$PATH" make check`: lint, formato, tipos estrictos y **93 tests aprobados**, sin skips.
- Pruebas deliberadas independientes, solo con directorios temporales y secretos ficticios: `.venv/bin/python /tmp/daily_digest_phase0_review.py`, **5/5 pasan** tras la corrección. El archivo temporal es apoyo de esta sesión; la regresión del hallazgo permanece en el repositorio.

| Contrato revisado | Implementación y prueba | Resultado del intento de rotura |
| --- | --- | --- |
| CB-01: paquete y CLI con operaciones pendientes explícitas | `pyproject.toml`, `src/digest/cli.py`; `tests/unit/test_cli.py` | Ayuda disponible; comandos futuros no simulan éxito. |
| CB-02: YAML estricto, rutas, claves desconocidas y tipos | `src/digest/config.py:241`; `tests/unit/test_config.py` | Se rechazan tipos erróneos y extras sin mostrar valores; corregido el caso de clave dinámica. |
| CB-03: WAL, claves foráneas y migraciones idempotentes | `src/digest/db/__init__.py`; `tests/unit/test_db.py` | Tres aplicaciones consecutivas preservan datos; duplicado de proyecto y CHECK de intervalo inválido rechazados en la prueba independiente. La suite cubre también UNIQUE de evidencia, rollback y versión futura. |
| CB-04 / T09: confinamiento y lectura acotada | `src/digest/util/fs.py:46`, `:78`; `tests/unit/test_fs.py` | `../`, ruta absoluta, enlace externo y bucle rechazados; nombres con comillas, `$()` y salto de línea leídos literalmente sin crear marcador. La suite cubre sustitución por enlace, exclusiones y cambios durante lectura. |
| CB-04 / T08: procesos sin shell y entorno mínimo | `src/digest/util/proc.py:21`; `tests/unit/test_proc.py` | Cadena rechazada; variable secreta ficticia ausente del hijo; `GIT_OPTIONAL_LOCKS=0` confirmado. |
| CB-05: fixtures reproducibles y dobles locales | `tests/fixtures/make_projects.py`, `tests/fixtures/doubles.py`; `tests/integration/test_fixtures.py` | Kanvas fijado por hash, historial reproducible, SMTP local normal e incierto y copia inmutable local aprobados. |
| CB-06: doctor de lectura y solicitudes sintéticas | `src/digest/doctor.py:130`; `tests/unit/test_doctor.py` | Doctor offline con clave ficticia no la imprime; dobles verifican petición sintética, errores redactados y SMTP sin envío. Los árboles sintéticos, incluido `.git`, permanecen iguales tras doctor offline. |

Los FR completos de captura, entrega, LLM y revisión humana corresponden a fases posteriores. En esta fase se revisaron los contratos de configuración y diagnóstico que los soportan y los invariantes de rutas, procesos y secretos. La comprobación real de dos pilotos y servicios se conoce por los hallazgos documentados de CB-06; no se ha repetido en esta sesión y requiere la firma humana prevista.

## Excepciones «gate: allow» revisadas

- `scripts/phase_gate.py:155`: justificada la llamada directa a `subprocess.run` en el script de desarrollo de la puerta, fuera de `src/digest`; ejecuta listas de comandos definidos en `docs/gates.toml`, con timeout y sin shell. No es una vía de ejecución de contenido de proyectos.
- `scripts/phase_gate.py:212` (llamada iniciada en `:208`): misma justificación para ejecutar pytest con una lista de argumentos construida por la puerta. La herencia del entorno permite localizar las herramientas de desarrollo; el wrapper de producción conserva su entorno mínimo. No hay excepciones `gate: allow` en código de producción.

## Veredicto del revisor

**Aprobada la revisión independiente de fase 0**, tras corregir y volver a probar el único hallazgo bloqueante. La aprobación de esta capa no aprueba por sí sola la puerta: falta la comprobación y firma de la persona. Los límites de contexto internos permanecen explícitamente sin medir y no se han dado por verificados. Se mantienen `builder: codex-builder` y todas las casillas humanas originales sin marcar.

## Firma de la persona

Comprobaciones que solo puedes hacer tú:

- [ ] digest doctor pasa en el equipo de Rocky con los dos proyectos piloto
- [ ] Los hallazgos de la verificación de contratos están en docs/DECISIONS.md
- [ ] Las preguntas Q-01, Q-06 y Q-07 tienen respuesta

- [ ] Apruebo la fase
