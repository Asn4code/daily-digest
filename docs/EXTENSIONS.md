# Extensiones: del resultado revisado a otros contenidos

daily-digest **no genera** material docente, protocolos ni textos de métodos. Hace tres cosas que lo hacen posible desde otras herramientas:

1. **Detecta oportunidades:** un resultado revisado que da para un protocolo, una clase o una sección de métodos.
2. **Prepara un *brief*:** un paquete de contexto con las evidencias, tu explicación revisada, su procedencia y unas instrucciones de generación.
3. **Documenta y expone dónde está la información**, para que Claude, un agente de código u otra herramienta generen el contenido con datos verificables.

Cada tipo de contenido es una **extensión** que se añade sin tocar el núcleo.

## 1. Por qué fuera del núcleo

| Motivo | Consecuencia |
| --- | --- |
| El núcleo existe para que entiendas lo que produces; generar más texto cada noche va en contra | Las oportunidades salen solo en el informe semanal (máximo 3), nunca en el diario |
| Un protocolo o una clase solo tienen valor si entiendes lo que explican | Solo los resultados con revisión cerrada por ti (`closed_by_human`) alimentan un brief |
| Docencia y protocolos tienen otro ritmo, otro público y otro nivel de exigencia | La generación ocurre cuando tú decides, en la herramienta adecuada, con tu autoría |
| Las herramientas de generación cambian más rápido que este servicio | El contrato estable es el paquete de contexto, no el generador |

Si un tipo de brief se usa mucho y la generación externa se vuelve repetitiva, se puede añadir más adelante una capacidad `draft` a esa extensión (ver §7). No forma parte del plan actual.

## 2. Dónde vive cada información

Mapa para cualquier herramienta o persona que quiera generar contenido desde el trabajo registrado:

| Información | Dónde está | Cómo se accede |
| --- | --- | --- |
| Tareas, decisiones del día a día, resúmenes de los agentes | `kanvas.json` de cada proyecto | Evidencias `task_*` en SQLite; brief §3 |
| Código, parámetros, historia de cambios | Repositorio Git del proyecto | Evidencias `commit`/`diff` con SHA; ruta del repo en el brief |
| Métricas y tablas de resultados | Archivos de `results/` declarados en la configuración | Evidencias `metric` con valores extraídos por código |
| Figuras | Ruta original en el proyecto; miniatura en `data_dir/` | Evidencias `figure`; PNG incluido en el brief |
| Ejecuciones (Slurm, Snakemake, Nextflow) | `sacct` y logs del proyecto | Evidencias `run`/`run_error` |
| Tu explicación de un resultado, el contraste y tu decisión | Tabla `review`; `Revisiones/` en Obsidian; Drive | Brief §3 (`review`) |
| Informes diarios y semanales | `Digest/` en Obsidian; `DailyDigest/` en Drive | Enlaces en el brief |
| Por qué se hizo cada cambio | Transcripciones de agentes (fase 2) | Evidencias `agent_session` resumidas |
| Objetivo de cada proyecto | `config.yaml` → `projects[].objective` | Brief §3 (`project`) |

## 3. El paquete de contexto (`context-pack`)

Formato estable y versionado. Un brief es una carpeta (y un zip con lo mismo):

```text
briefs/2026-11-08-protocol-res_proj-a_DV-03/
  manifest.json         # tipo, versión, origen, fecha, extensión que lo creó
  context.json          # datos estructurados (abajo)
  context.md            # lo mismo legible para una persona o un modelo
  instructions.md       # qué generar, para quién, con qué reglas (de la extensión)
  figures/*.png
```

`context.json` (versión 1):

```json
{
  "pack_version": 1,
  "kind": "protocol",
  "created_at": "2026-11-08T10:12:00Z",
  "language": "es",
  "audience": "personas del grupo que repetirán el análisis",
  "project": { "id": "proj-a", "name": "Proyecto A", "objective": "…" },
  "results": [
    {
      "id": "res_proj-a_DV-03",
      "title": "…",
      "kanvas_task": "DV-03",
      "summary": "…",
      "review": {
        "state": "closed_by_human",
        "mode": "full",
        "human_text": { "purpose": "…", "observation": "…", "limits": "…", "consequence": "…" },
        "contrast": { "supported": [], "omissions": [], "unsupported": [], "unverifiable": [] },
        "decided_at": "2026-11-06T21:40:00Z"
      },
      "evidence": [
        { "id": "ev_…", "kind": "run", "locator": "slurm:123456", "event_at": "…", "excerpt": "…" }
      ],
      "parameters": [ { "name": "…", "value": "…", "evidence": "ev_…" } ],
      "metrics": [ { "name": "rmsd_mean", "value": 1.8, "unit": "Å", "evidence": "ev_…" } ],
      "figures": [ { "evidence": "ev_…", "file": "figures/rmsd.png", "caption": "…" } ]
    }
  ],
  "open_questions": [ "…" ],
  "sources": {
    "repositories": [ { "path": "/home/USER/proyectos/proj-a", "commits": ["abc1234"] } ],
    "kanvas_tasks": ["DV-03"],
    "obsidian_notes": ["Revisiones/2026-11-06-res_proj-a_DV-03.md"],
    "drive_paths": ["DailyDigest/2026/11/2026-11-06/"]
  },
  "constraints": { "external_allowed": true, "cite_evidence_ids": true }
}
```

Reglas del paquete:

- Solo incluye resultados con revisión `closed_by_human`. Si falta, el brief no se crea y la webapp propone revisar primero.
- Cada parámetro, cifra y figura lleva su ID de evidencia; el generador externo debe conservarlos como referencias.
- Respeta `external_allowed` y las exclusiones del proyecto; nunca incluye secretos ni archivos excluidos.
- Incluye las dudas abiertas y las omisiones del contraste: lo que todavía no sabes también va al paquete.

## 4. Contrato de una extensión

Extensiones internas en `src/digest/extensions/<nombre>/`; externas como paquetes Python que declaran el punto de entrada `daily_digest.extensions`. El núcleo las descubre con `importlib.metadata.entry_points`.

```python
class Extension(Protocol):
    name: str              # "protocol"
    title: str             # "Protocolo o metodología"
    version: str           # "1"
    capabilities: set[Literal["detect", "brief"]]   # "draft" reservado para el futuro

    def detect(self, ctx: DetectContext) -> list[OpportunityDraft]:
        """Lee el registro (solo lectura) y propone oportunidades con su motivo."""

    def build_brief(self, opportunity: Opportunity, ctx: BriefContext) -> BriefDraft:
        """Devuelve la selección de resultados, la audiencia y el texto de instructions.md.
        El núcleo construye y valida el paquete; la extensión no escribe archivos."""
```

```text
src/digest/extensions/protocol/
  extension.py          # clase que cumple el contrato
  instructions.md       # plantilla de instrucciones para el generador
  manifest.toml         # name, title, version, capabilities, reglas de detección
```

Lo que una extensión **no puede** hacer: escribir en el registro salvo a través del núcleo, leer archivos de proyectos directamente (usa las evidencias ya capturadas), llamar a proveedores LLM, enviar correos ni publicar nada. Los invariantes de `AGENTS.md` se aplican igual.

## 5. Extensiones previstas

| Extensión | Qué prepara | Señales para proponerla | Destino típico |
| --- | --- | --- | --- |
| `protocol` | Protocolo o metodología para compartir: pasos, parámetros, controles, criterios de éxito, problemas conocidos | Resultado cerrado con ejecuciones correctas repetidas del mismo pipeline; o etiqueta `#protocolo` en una nota de Kanvas | Documento del grupo, repositorio de protocolos |
| `teaching` | Material docente: explicación por niveles, figura comentada, preguntas para comprobar comprensión | Revisión cerrada en modo completo con contraste mayoritariamente respaldado; o `#docencia` | Clase, seminario, guía para estudiantes |
| `methods` | Borrador de sección de métodos | Varios resultados cerrados de un proyecto con figuras y parámetros | Artículo, informe de proyecto |
| `group-meeting` | Guion de presentación de avances | Semana con resultados cerrados y decisiones | Reunión de grupo |

Prioridad inicial acordada (Q-13, D-040): protocolos reproducibles para la persona
y colaboradores, primero; métodos para artículos, después. Docencia y reuniones
se priorizarán según necesidades, conservando las extensiones previstas. Los
protocolos se orientan inicialmente a Markdown con pasos, parámetros, controles,
criterios de éxito y problemas conocidos.

Las oportunidades se proponen en el informe semanal (sección «Oportunidades», máximo 3) y en la pantalla Oportunidades de la webapp. También se puede pedir un brief de cualquier resultado cerrado desde su pantalla de detalle o con `digest brief <tipo> <result_id>`.

## 6. Cómo se genera el contenido fuera

| Herramienta | Cómo usa el brief |
| --- | --- |
| Claude (chat o proyecto) | Subir el zip del brief o abrirlo desde Drive; `instructions.md` sirve como petición |
| Agente de código (Claude Code, Codex…) | Leer la carpeta del brief; una skill propia puede fijar el formato de salida del grupo |
| Servidor MCP de solo lectura (fase 6) | El asistente consulta directamente el registro: `search_results`, `get_result`, `get_evidence`, `list_reviews`, `list_opportunities`, `get_brief`. Sin herramientas de escritura |

Preferencia de generación externa (Q-14, D-037): Qwen y los modelos de NaN
son las opciones por defecto, con elección según la tarea. La persona puede pedir
que Claude o Codex generen o rehagan el contenido a partir del mismo brief.
Proveedor/modelo y herramienta son decisiones distintas: el paquete no queda
ligado a un único asistente. Rehacer produce una versión nueva y conserva el
original y las aportaciones humanas. Esta preferencia orienta el flujo externo;
no habilita llamadas de generación de contenido dentro del núcleo ni de las
extensiones.

El contenido generado vuelve como un archivo normal (Drive, Obsidian o el repositorio que elijas); daily-digest no lo almacena ni lo revisa. Si quieres que quede constancia, enlázalo en la nota de la oportunidad (`brief_used` → URL).

## 7. Añadir una extensión nueva

1. Crear `src/digest/extensions/<nombre>/` (o un paquete externo con el punto de entrada).
2. Implementar `detect` (reglas sobre el registro) y `build_brief`.
3. Escribir `instructions.md` pensando en el generador: público, estructura esperada, reglas (citar IDs de evidencia, separar observación de interpretación, incluir límites y dudas).
4. Añadir tests: el escenario T35 exige que una extensión de prueba se registre y genere un brief sin tocar el núcleo.
5. Anotar la extensión en esta página y en `DECISIONS.md`.

Una futura capacidad `draft` (la extensión genera un primer borrador con el LLM) exigiría: borrador marcado como tal, todas las afirmaciones validadas contra el paquete, y que nunca se envíe ni se publique sin tu acción.
