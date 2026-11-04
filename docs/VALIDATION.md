# Validación por fases

Cada fase termina en una **puerta**: no se empieza la siguiente hasta que la puerta está aprobada. Una puerta tiene tres capas, y las tres deben pasar:

| Capa | Quién | Qué comprueba | Dónde queda |
| --- | --- | --- | --- |
| 1. Automática | `scripts/phase_gate.py` | Archivos, reglas prohibidas, lint y tipos, tests de los escenarios exigidos (con regresión de fases anteriores), tareas del grupo en `done` | `build/gates/phase-N.md` |
| 2. Revisión independiente | Un agente **distinto** del que construyó (otra herramienta, o una sesión nueva sin el contexto de construcción) | Lo que un test no ve: que el código cumple la especificación y los invariantes, e intentos deliberados de romperlo | `docs/reviews/phase-N.md`, «Hallazgos» y «Veredicto» |
| 3. Firma humana | La persona | Lo que solo ella puede juzgar: utilidad, legibilidad en el móvil, comportamiento en su equipo real | `docs/reviews/phase-N.md`, «Firma» |

## 1. Flujo en el tablero

Cada grupo de Kanvas termina con una tarea «Puerta de fase N» que depende de todas las demás tareas del grupo, y las primeras tareas de la fase siguiente dependen de esa puerta. Así el tablero bloquea por sí solo el avance.

1. **Constructor** (el agente que hizo la fase), con la tarea de puerta en `doing`:
   ```bash
   python scripts/phase_gate.py N --no-manual    # debe dar PROVISIONAL (código 3), nunca SUSPENDIDA
   python scripts/phase_gate.py N --init-review  # crea docs/reviews/phase-N.md
   ```
   Rellena `builder:` en la ficha, adjunta el informe y deja una nota en la tarea con `kanvas note`.
2. **Revisor** (agente distinto): sigue el prompt de la sección 4, escribe hallazgos y veredicto en la ficha. Si hay hallazgos bloqueantes, el constructor los corrige y se repite desde el paso 1.
3. **Persona**: hace las comprobaciones manuales de la ficha, marca cada una y la casilla «Apruebo la fase».
4. **Constructor**: ejecuta la puerta completa y, si da APROBADA (código 0), hace `finish` de la tarea de puerta con el informe. La persona la mueve a `done`.

```bash
python scripts/phase_gate.py N          # APROBADA (0) · SUSPENDIDA (1) · PROVISIONAL (3)
python scripts/phase_gate.py N --host   # en el equipo de Rocky: añade comprobaciones de systemd y doctor real
```

Una ejecución con `--only` nunca aprueba una fase. Una puerta aprobada se vuelve a ejecutar sin cambios en la fase siguiente (regresión), así que una fase posterior no puede romper una anterior sin que se note.

## 2. Qué comprueba la capa automática

Definido en `docs/gates.toml`:

- **Archivos** que cada fase debe dejar creados.
- **Reglas prohibidas** en el código, una por invariante de `AGENTS.md`: `shell=True`, `os.system`, `subprocess` fuera de `util/proc.py`, operaciones destructivas de rclone, `autoescape=False`, `|safe` en plantillas, CDN, `eval`/`exec`, `pickle`/`yaml.load`, secretos escritos en el código. Una línea concreta se puede exceptuar con `# gate: allow <id> <motivo>`; la puerta la marca como WARN y el revisor debe justificar cada excepción en la ficha.
- **Comandos**: `ruff check`, `ruff format --check`, `mypy` y los propios de la fase (por ejemplo, `digest run --now --no-send` contra los fixtures). Los marcados `host_only` solo corren con `--host`.
- **Tests por escenario**: cada ID de `TESTING.md` exigido en la fase (y en las anteriores) debe tener al menos un test con ese ID en el nombre, y todos deben pasar. Un test omitido (`skip`) cuenta como fallo.
- **Tablero**: todas las tareas del grupo de la fase en `done`, salvo la propia puerta.

Para cambiar qué exige una puerta se edita `gates.toml` y se anota el motivo en `DECISIONS.md`; rebajar una exigencia requiere aprobación de la persona.

## 3. Lo que el revisor debe intentar en cada fase

Además de leer el código frente a la especificación, el revisor **intenta romperlo**. Cada intento que no esté cubierto por un test se convierte en un hallazgo con la propuesta de test.

### Fase 0. Contratos y base

- `util.fs.safe_path` con `../`, rutas absolutas, enlace simbólico fuera de la raíz, bucle de enlaces y nombres con `$()`, comillas y saltos de línea.
- `util.proc.run` con una cadena en lugar de lista: debe rechazarla. Comprobar que el entorno pasado al proceso no hereda variables con secretos.
- Configuración con claves desconocidas o tipos erróneos: debe fallar con un mensaje claro (`extra="forbid"`).
- Migraciones aplicadas dos veces; restricciones `CHECK` y `UNIQUE` probadas.
- `digest doctor` con una clave falsa en el entorno: la clave no aparece en la salida ni en los logs.

### Fase 1. Captura e informe mecánico

- Hash de cada árbol de fixtures antes y después de la suite completa (T30), incluido `.git/index`.
- Dos capturas seguidas sin cambios: ninguna evidencia duplicada.
- Un archivo que cambia mientras se lee; un `kanvas.json` con `"kanvas": 2`; un `.xtc` enorme; un directorio sin permisos.
- Cada evidencia tiene `time_quality` correcto: `event` solo si viene de una nota o commit fechado.
- Nota de Kanvas con `<script>` y con Markdown malicioso: escapada en correo y Obsidian.
- `rclone copy --immutable` dos veces con el archivo local cambiado: no sobrescribe el remoto.
- Correo: `Message-ID` estable al regenerar; versión en texto plano completa.

### Fase 2. Informe con LLM

- `FakeLLM("liar")` con un ID inventado, una cifra inventada y una cifra correcta con otra unidad.
- README con instrucciones para el agente: ningún efecto en la salida ni en las acciones.
- Abrir 5 afirmaciones al azar de un informe de fixtures y comprobar a mano que sus evidencias las sostienen.
- Proyecto con `external_allowed = false`: ninguna fila de `llm_call` con proveedor `nan` para sus evidencias.
- Proveedor preferido caído: el informe dice qué proveedor generó cada sección.
- Prompts: todos delimitan las evidencias, piden IDs y prohíben inventar cifras.

### Fase 3. Webapp y revisión

- Formularios sin token CSRF y con token de otra sesión; cabecera `Tailscale-User-Login` de otro usuario.
- Cargas XSS en notas, salidas del modelo y texto humano; comprobar la cabecera CSP.
- Rutas de archivos con `../` o IDs inexistentes: 404, nunca lectura fuera de `data_dir/reports/`.
- Ningún camino cambia `review_state` a `closed_by_human` sin `POST /review/{id}/decide`.
- El proceso web no ejecuta trabajos: lanzar un informe desde Generar y comprobar que lo procesa el worker.
- Captura de la pantalla Hoy y Revisar a 390 px de ancho (Playwright) adjunta en la ficha.

### Fase 4. Operación

- `systemd-analyze verify` y `systemd-analyze security` de las unidades (exposición ≤ 5.0).
- Desde el servicio en marcha, intentar escribir un archivo de control en un proyecto: debe fallar con sistema de archivos de solo lectura.
- `kill -9` del worker a mitad de un informe y reinicio: sin resultados duplicados (T29).
- Cortar la red durante la subida a Drive y restaurarla: las entregas pendientes suben (T27).
- Restauración completa en un directorio limpio desde la copia de Drive (T28).

### Fase 5. Piloto

- Comprobar que los datos del piloto están completos y que la evaluación propone ajustes concretos, cada uno con su motivo.

### Fase 6. Extensiones

- Pedir un brief de un resultado sin revisión cerrada, con revisión `postponed` y con revisión de otro resultado: ninguno se crea (T31).
- Abrir `context.json` y comprobar que cada parámetro, cifra y figura tiene un ID de evidencia existente, y que no aparece ningún archivo excluido ni secreto (T32).
- Proyecto con `external_allowed = false`: su contenido no sale por el servidor MCP ni en briefs marcados para herramientas externas.
- Listar las herramientas del servidor MCP e intentar cualquier escritura: imposible (T34).
- Una extensión que intenta abrir un archivo de proyecto o llamar a un proveedor LLM: el contrato no se lo permite o un test lo detecta.
- Instalar una extensión externa de prueba y comprobar que no hizo falta tocar `src/digest` fuera de `extensions/` (T35).

## 4. Prompt para el agente revisor

Copiar en una sesión nueva de un agente distinto del constructor, sustituyendo `N`:

```text
Eres el revisor independiente de la fase N del repositorio daily-digest. No has participado en su construcción.

1. Lee AGENTS.md, docs/SPEC.md, docs/VALIDATION.md (secciones 2 y 3, fase N), docs/ROADMAP.md (fase N)
   y los documentos de área que correspondan a la fase.
2. Ejecuta `python scripts/phase_gate.py N --no-manual` y lee build/gates/phase-N.md.
   Si no da PROVISIONAL, detente y anota los fallos como bloqueantes.
3. Revisa el código de la fase frente a la especificación y los invariantes. Para cada requisito FR de la fase,
   localiza dónde se cumple y qué test lo prueba.
4. Haz los intentos de rotura de VALIDATION.md §3 para la fase N. No modifiques código de producción;
   puedes escribir tests nuevos en una rama aparte si ayudan a demostrar un fallo.
5. Revisa cada excepción `gate: allow` y di si está justificada.
6. Escribe en docs/reviews/phase-N.md:
   - reviewer: tu herramienta (p. ej. codex) y date
   - Hallazgos: una línea por hallazgo, con severidad (**bloqueante**, **importante**, **menor**),
     archivo y línea, cómo reproducirlo y el test que lo cubriría. Si no hay bloqueantes, borra la línea
     de ejemplo «bloqueante».
   - Veredicto: «aprobada» solo si no queda ningún bloqueante; si no, «cambios».
7. No marques las comprobaciones de la sección «Firma»: son de la persona.
Sé concreto y escéptico. Un hallazgo sin forma de reproducirlo no sirve; una aprobación sin intentos de rotura tampoco.
```

## 5. Severidad de los hallazgos

| Severidad | Ejemplos | Efecto |
| --- | --- | --- |
| Bloqueante | Rompe un invariante; un escenario exigido no está cubierto de verdad; un test pasa sin probar lo que dice; pérdida de datos posible | La puerta no se aprueba hasta resolverlo |
| Importante | Requisito cumplido a medias; mensaje de error confuso; caso límite sin test | Se resuelve en la fase o se propone como tarea con `kanvas propose` |
| Menor | Estilo, nombres, documentación | Opcional |
