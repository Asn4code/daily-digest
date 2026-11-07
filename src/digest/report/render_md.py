"""Render orientation, conceptual understanding and expandable technical evidence."""

import html
import json
import re
from typing import Any

from digest.report.model import Report
from digest.report.observations import normalize, origin_label
from digest.report.timeutil import display
from digest.report.views import CONFIDENCE, PRIORITIES, daily_view, weekly_checks, weekly_notices


def escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", html.escape(text))


def claim(value: dict[str, Any]) -> str:
    return escape(value["text"]) + " [" + ", ".join(value["evidence"]) + "]"


def claims(values: list[dict[str, Any]]) -> list[str]:
    return [claim(value) for value in values]


def interpretation(value: dict[str, Any]) -> str:
    return "Interpretación (confianza " + CONFIDENCE[value["confidence"]] + "): " + claim(value)


def render(report: Report) -> str:
    view = daily_view(report)
    weekly = report.sections.get("weekly")
    label = "Borrador pendiente · informe" if report.pending else "Informe"
    lines = [
        f"# {label} {report.kind_label}",
        f"{display(report.start_at, report.timezone)} — {display(report.end_at, report.timezone)}",
    ]
    if report.pending:
        lines.extend(
            [
                "Generación incompleta. Sin entrega final ni cierre del intervalo.",
                "## Secciones pendientes",
            ]
        )
        for key, issues in sorted(report.pending.items()):
            lines.append(
                escape(key)
                + ": "
                + "; ".join(
                    escape(i["category"] + "/" + i["rule"] + " · " + i["field"]) for i in issues
                )
            )
    if any(r.reference_only for r in report.results):
        lines.append("Incluye contexto histórico; no todo representa trabajo de hoy.")
    lines.append("## Lo esencial · orientación")
    if weekly:
        highlighted = weekly_checks(report, highlighted=True)
        if highlighted:
            for check in highlighted:
                lines.extend(
                    [
                        check["label"] + " · " + escape(check["prior"]["project_id"]),
                        interpretation(check["assessment"]),
                        "Límite decisivo: " + claim(check["decisive_limit"]),
                        "Consecuencia para el foco: " + claim(check["focus_implication"]),
                    ]
                )
        else:
            lines.extend(claims(weekly["patterns"][:3]))
    elif view.highlights:
        for item in view.highlights:
            lines.extend(
                [
                    claim(item["observation"]),
                    interpretation(item["meaning"]),
                    "Límite decisivo: " + claim(item["decisive_limit"]),
                ]
            )
    elif not report.pending and not any(not r.reference_only for r in report.results):
        lines.append(
            "Sin novedades verificadas del intervalo. La referencia inicial o histórica "
            "queda disponible en el inventario; no se ha solicitado su interpretación "
            "científica en este diario."
        )
    elif not report.pending:
        lines.append(view.orientation_notice)
    else:
        lines.append("Orientación pendiente de validación.")
    lines.append("## Balance conceptual")
    for project in view.projects:
        context = report.project_context.get(project["project_id"], {})
        lines.append("### " + escape(context.get("name", project["project_id"])))
        if context.get("objective"):
            lines.append("Objetivo declarado: " + escape(context["objective"]))
        lines.extend([claim(project["explanation"]), interpretation(project["importance"])])
        lines.extend(claims(project["known_now"]))
        lines.append("Qué sigue abierto")
        lines.extend(claims(project["still_unknown"]))
        lines.extend(claims(project["decisions_changed"]))
        if project["no_new_conclusion"]:
            lines.append("No hay conclusión científica nueva en las fuentes analizadas.")
    if weekly:
        for project in weekly["projects"]:
            lines.append("### " + escape(project["project_id"]))
            lines.extend(claims(project["progress_vs_objective"]))
            lines.extend(claims(project["decisions"]))
            lines.extend(interpretation(value) for value in project["hypotheses_changed"])
    if report.kind == "weekly":
        lines.append("## Contraste crítico semanal")
        lines.extend(claims(weekly_notices(report)))
        for check in weekly_checks(report):
            prior = check["prior"]
            lines.extend(
                [
                    "### " + check["label"] + " · " + escape(prior["result_id"]),
                    "Declaración anterior: " + escape(prior["text"]),
                    "Autor: " + escape(prior["author"]) + " · Versión: " + escape(prior["version"]),
                    "Fecha de referencia: " + display(prior["source_date"], report.timezone),
                    "Estado humano conservado: " + escape(prior["review_state"]),
                    "Alcance y condiciones originales: "
                    + escape(json.dumps(prior["scope"], ensure_ascii=False)),
                    "Fuentes anteriores: " + ", ".join(prior["evidence"]),
                    "Fuentes nuevas: " + ", ".join(check["new_evidence"]),
                    "Comparabilidad: " + claim(check["comparability"]),
                    interpretation(check["assessment"]),
                    "Límite decisivo: " + claim(check["decisive_limit"]),
                    "Consecuencia para el foco: " + claim(check["focus_implication"]),
                ]
            )
            if prior["author"] == "automatic":
                lines.append("Interpretación automática histórica; no declara tu posición actual.")
            later = prior.get("later_automatic_interpretation")
            if later:
                lines.extend(
                    [
                        "Versión automática posterior como contexto: " + escape(later["version"]),
                        escape(later["text"]) + " [" + ", ".join(later["evidence"]) + "]",
                        "No representa aceptación humana ni un descubrimiento nuevo del semanal.",
                    ]
                )
            lines.extend(claims(check["alternative_explanations"]))
            for analysis in check["analyses"]:
                lines.extend(
                    [
                        "#### Análisis propuesto · " + escape(analysis["question"]),
                        "Datos necesarios: " + escape(analysis["required_data"]),
                        "Control: " + escape(analysis["control"]),
                        "Dependencia: " + escape(analysis["dependency"] or "Ninguna declarada"),
                        "Alternativas: " + "; ".join(escape(t) for t in analysis["alternatives"]),
                        *[
                            "Predicción para "
                            + escape(p["alternative"])
                            + ": "
                            + escape(p["expected_observation"])
                            for p in analysis["predictions"]
                        ],
                        "Criterio de decisión: " + escape(analysis["decision_criterion"]),
                        "Motivado por: " + ", ".join(analysis["evidence"]),
                        "Propuesta; no ejecutada por el servicio.",
                    ]
                )
    lines.append("## Todo lo hecho y contexto observado")
    if not report.results:
        lines.append(
            "Sin resultados verificables en este intervalo. "
            "Esto no demuestra que no se haya trabajado."
        )
    for result in report.results:
        lines.extend(
            [
                "### " + escape(result.project) + " · " + escape(result.title),
                "Tarea: "
                + escape(result.task_id or "fuera del tablero")
                + " · Revisión: "
                + escape(result.review_label),
                "Referencia inicial/histórica; no acredita trabajo nuevo."
                if result.reference_only
                else "Resultado del intervalo.",
                "Evidencias: " + ", ".join(result.evidence),
            ]
        )
        card = view.cards.get(result.id)
        if card:
            if card["question"]:
                lines.append("Pregunta: " + claim(card["question"]))
            lines.extend(claims(card["observations"]))
            if card["meaning"]:
                lines.append(interpretation(card["meaning"]))
            lines.append("Controles y condiciones")
            lines.extend(claims(card["controls"]))
            lines.append("Límites")
            lines.extend(claims(card["limits"]))
            if card["decision_impact"]:
                lines.append("Consecuencia: " + claim(card["decision_impact"]))
            if card["next_question"]:
                lines.append("Pregunta pendiente: " + claim(card["next_question"]))
        elif not result.reference_only:
            extracted = report.sections.get("extract:" + result.id)
            if extracted:
                lines.append(
                    "Pieza de fuente validada; explicación integrada pendiente."
                    if report.pending
                    else "Síntesis de las fuentes"
                )
                for source in extracted["sources"]:
                    lines.extend([claim(source["summary"]), *claims(source["observations"])])
                    lines.extend(interpretation(value) for value in source["interpretations"])
                    lines.extend(claims(source["controls"]))
                    lines.extend(claims(source["limitations"]))
            else:
                lines.append("Explicación pendiente.")
        for figure in result.figures:
            lines.append(f"![{escape(figure.caption)}]({figure.path}) · {figure.evidence}")
    lines.append(
        "## Propuesta de semana" if report.kind == "weekly" else "## Plan de mañana · próximo foco"
    )
    if view.planning_for:
        lines.append(
            "Orientado al " + escape(view.planning_for) + ". La elección sigue siendo tuya."
        )
    if view.accepted:
        accepted = view.accepted
        lines.extend(
            [
                "### Plan aceptado por la persona",
                escape(accepted["edited_text"] or accepted["action"]),
                "Terminado cuando: " + escape(accepted["done_criterion"]),
            ]
        )
        if accepted.get("dependency"):
            lines.append("Dependencia: " + escape(accepted["dependency"]))
        if view.carry_forward:
            lines.append("Se conserva el plan aceptado.")
    if view.change_reason:
        lines.append("Motivo para reconsiderar el foco: " + claim(view.change_reason))
    proposed = (
        weekly["next_week"] if weekly else ([view.mission] if view.mission else []) + view.warmups
    )
    for item in proposed:
        lines.extend(
            [
                "### Propuesta: " + escape(item["action"]),
                "Terminado cuando: " + escape(item["done_criterion"]),
                "Dependencia: " + escape(item["dependency"] or "Ninguna declarada"),
                "Motivo: " + escape(item["reason"]) + " [" + ", ".join(item["evidence"]) + "]",
                "Origen: " + escape(item["origin"]),
            ]
        )
        if item.get("project_id"):
            lines.append("Proyecto: " + escape(item["project_id"]))
        if item.get("priority_basis"):
            lines.append(
                "Prioridad por: " + ", ".join(PRIORITIES[basis] for basis in item["priority_basis"])
            )
        if item.get("decision_unlocked"):
            lines.append("Decisión que ayudaría a tomar: " + escape(item["decision_unlocked"]))
        if item.get("uncertainty_addressed"):
            lines.append("Duda o control: " + claim(item["uncertainty_addressed"]))
    if view.no_mission_reason:
        lines.append("Sin misión nueva propuesta: " + claim(view.no_mission_reason))
    elif report.pending and not proposed:
        lines.append("Propuesta pendiente de validación.")
    elif not proposed and not view.carry_forward:
        lines.append("Sin misión nueva propuesta.")
    lines.append("## Hilos abiertos")
    lines.extend(
        escape(value.text) + " [" + ", ".join(value.evidence) + "]" for value in report.open_threads
    )
    for key, value in report.sections.items():
        if key.startswith("extract:"):
            lines.extend(c for source in value["sources"] for c in claims(source["open_questions"]))
    if weekly:
        lines.extend(
            [
                "## Revisiones de la semana",
                "Cerradas por la persona: " + ", ".join(weekly["review_status"]["completed"]),
                "Pendientes (de mayor a menor antigüedad): "
                + ", ".join(weekly["review_status"]["pending"]),
                *claims(weekly["review_status"]["doubts"]),
                "## Patrones",
                *claims(weekly["patterns"]),
                "## Figuras clave",
                ", ".join(weekly["key_figures"]) or "No hay figuras disponibles.",
            ]
        )
    lines.append("## Nivel técnico y evidencias")
    for entry in report.evidence:
        observed = report.observations.get(entry.id, normalize(entry))
        technical = [
            f"### {entry.id}",
            f"{escape(entry.project)} · {escape(entry.kind)} · {escape(entry.locator)}",
            f"Hora: {display(entry.event_at or entry.observed_at, report.timezone)} "
            f"({'evento' if entry.time_quality == 'event' else 'observada'})",
            "Origen: " + escape(origin_label(observed["origin"])),
            *(escape(text) for text in observed["limitations"]),
            escape(entry.excerpt),
        ]
        for fact in observed["computed"]:
            technical.append(
                escape(fact["column"] + " / " + fact["operation"] + " / " + fact["statistic"])
                + ": "
                + str(fact["value"])
                + " · unidad no declarada ["
                + entry.id
                + "]"
            )
        lines.append(
            "> [!info]- Comprobar "
            + entry.id
            + "\n"
            + "\n".join("> " + line for block in technical for line in block.splitlines())
        )
    lines.append("## Cobertura")
    for source in report.coverage:
        lines.append(
            f"- {escape(source.project)} / {source.source}: {source.status} "
            f"(captura {source.snapshot_id})"
        )
        lines.extend(
            "  - " + escape(o["locator"]) + ": " + escape(o["reason"]) for o in source.omitted
        )
    lines.extend(escape(warning) for warning in report.warnings)
    for section, model in report.model_info.items():
        lines.append(
            escape(section)
            + ": "
            + escape(model["provider"])
            + " / "
            + escape(model["model"])
            + " · prompt "
            + escape(report.prompt_versions[section])
        )
    return "\n\n".join(lines) + "\n"
