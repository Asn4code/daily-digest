# daily-digest

Servicio personal que, al final de cada día (o cuando lo pidas), reúne lo que has hecho en tus proyectos, te envía un correo con lo esencial y te deja en una webapp el informe completo y un resultado para revisar explicándolo con tus palabras. Los sábados genera un informe semanal más largo. Todo se copia en Obsidian y en tu Google Drive.

## Qué hace

- **Recoge evidencias** de Kanvas, Git, documentación, figuras, métricas y ejecuciones (Slurm, Snakemake, Nextflow), en solo lectura.
- **Genera informes** con Qwen (interno) y NaN (externo), con cada afirmación enlazada a sus evidencias.
- **Entrega** un correo esencial, el informe completo en la webapp, una copia en Obsidian y una copia remota continua en Google Drive.
- **Revisión activa:** propone un resultado al día; lo explicas con tus palabras y el sistema contrasta tu explicación con las evidencias. Nunca marca nada como comprendido por ti.
- **Extensiones:** detecta resultados revisados que dan para un protocolo, material docente o una sección de métodos, y prepara un paquete de contexto para generarlos con otras herramientas.

## Documentación

| Documento | Contenido |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Reglas para agentes de código: invariantes, stack, flujo con Kanvas |
| [docs/SPEC.md](docs/SPEC.md) | Requisitos funcionales y criterios de aceptación |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Módulos, esquema SQLite, configuración |
| [docs/EVIDENCE.md](docs/EVIDENCE.md) | Fuentes de evidencia y contrato de los recolectores |
| [docs/LLM.md](docs/LLM.md) | Enrutado de modelos, prompts, esquemas y validador |
| [docs/WEBAPP.md](docs/WEBAPP.md) | Pantallas, rutas, revisión y seguridad |
| [docs/EXTENSIONS.md](docs/EXTENSIONS.md) | Extensiones: dónde vive la información, paquete de contexto, contrato y cómo generar contenido fuera |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Despliegue en Rocky Linux 9: systemd, Tailscale, rclone, correo |
| [docs/TESTING.md](docs/TESTING.md) | Fixtures, dobles y escenarios obligatorios |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Fases y criterios de aceptación |
| [docs/VALIDATION.md](docs/VALIDATION.md) | Puertas de fase: comprobación automática, revisión independiente y firma |
| [docs/gates.toml](docs/gates.toml) | Qué exige la puerta de cada fase (lo lee `scripts/phase_gate.py`) |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decisiones y preguntas abiertas |

## Empezar

Estado de implementación: fases 0, 1 y 2 aprobadas; fase 3 en desarrollo.
Funcionan la captura de solo lectura, SQLite, los informes con LLM validados,
el plan propuesto, el contraste crítico semanal y las entregas a correo,
Obsidian y Drive. La webapp ya permite consultar Hoy, Semana, resultados e
Historial, escribir una explicación propia y contrastarla antes de decidir.
La pantalla Plan permite ajustar, aceptar o descartar el foco y conserva cada
decisión en Obsidian/Drive. Generar permite solicitar diario, semanal o avance,
seguir los trabajos y reintentar solo un canal fallido desde la web.
Los servicios systemd pertenecen a la fase 4.

```bash
kanvas init                                        # tablero y skill para agentes
kanvas batch --file docs/backlog.kanvas.json       # backlog inicial como propuestas
make setup && make check
python scripts/phase_gate.py 3 --no-manual        # estado de la puerta de la fase actual
.venv/bin/digest --config config.yaml web        # lectura local en 127.0.0.1:8090
```

Tras `make setup`, usa `.venv/bin/digest --help` o activa el entorno con
`source .venv/bin/activate`. `make check` ejecuta lint, formato, tipos estrictos y
tests. `make fixtures` genera los tres proyectos sintéticos en un directorio temporal
nuevo y su configuración en `tests/fixtures/config.yaml`. La instalación necesita
acceso a PyPI; los tests de integración requieren rclone y sockets de localhost.

## Configurar y añadir proyectos

Copia `config.example.yaml` a `config.yaml` (excluido de Git) y ajusta las rutas
absolutas y los servicios. `projects` es una lista ampliable: añade una entrada
por proyecto, con un `id` único y estable, nombre, raíz y objetivo. Puedes empezar
con `projects: []`. Por ejemplo:

```yaml
projects:
  - id: docking
    name: Docking
    root: /home/USER/proyectos/docking
    objective: Comparar los controles con los candidatos
    include: ["docs/**", "results/**"]
  - id: estructuras
    name: Estructuras
    root: /home/USER/proyectos/estructuras
    objective: Revisar la calidad de los modelos
    include: ["docs/**", "results/**"]
```

La configuración rechaza campos desconocidos, tipos incorrectos, IDs repetidos,
puertos y límites inválidos, y referencias a proveedores no declarados. Solo
contiene nombres de variables para las credenciales; no pegues claves. Los valores
del proveedor interno y las credenciales deben configurarse para cada instalación: validar el
YAML no significa que los servicios estén disponibles. La carga de configuración
no crea directorios ni accede a los proyectos o proveedores.


Para diagnosticar sin red ni procesos externos:

```bash
.venv/bin/digest --config config.yaml doctor --offline
```

El modo online comprueba Kanvas, hace peticiones LLM con datos sintéticos,
autentica SMTP sin enviar correo y consulta Drive y Tailscale. Un resultado offline
no acredita disponibilidad de esos servicios. Las credenciales se leen del entorno
o de `$CREDENTIALS_DIRECTORY/secrets.env`; no se importan desde OpenCode.

Puedes elegir los modelos editando `llm.providers.<nombre>.model` y el orden de
proveedores por tarea en `llm.routing`. Inicialmente se usa el Qwen interno para
extracción y DeepSeek de NaN para síntesis, plan, semanal y contraste, con respaldo
mutuo. La edición de modelos desde la webapp está propuesta en WA-06.

La sección **Tareas** de la webapp ofrece tarjetas y un grafo de dependencias de
Kanvas. Permite guardar notas personales y editar prioridades con aumento acotado
por antigüedad; los proyectos permanecen en solo lectura. Estas preferencias
alimentan el siguiente plan diario. Consulta [el cuaderno personal](docs/PERSONAL_NOTEBOOK.md)
para conocer sus reglas, historial y límites.


> La generación actual conserva el respaldo mecánico anterior: todavía no cumple
> el requisito nuevo de D-047. Las pruebas reales están detenidas mientras se
> prepara el [flujo jerárquico](docs/HIERARCHICAL_DIGEST.md).

## Capturar, generar y entregar

```bash
.venv/bin/digest --config config.yaml capture
.venv/bin/digest --config config.yaml run --now --no-send
.venv/bin/digest --config config.yaml run --preview --now
```

`--no-send` guarda el informe local sin entregarlo; un avance tampoco cierra el
intervalo. Para entregar un informe ya comprobado, usa `digest deliver --report ID`.
Sin `--now`, `run` solo encola: `digest worker --once` procesa un trabajo pendiente.
El envío lee las credenciales del entorno o de `$CREDENTIALS_DIRECTORY/secrets.env`.
Los reintentos y los estados inciertos se explican en [OPERATIONS.md](docs/OPERATIONS.md).
