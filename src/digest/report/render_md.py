"""Render Markdown with all project-authored text escaped."""

import html
import re
from typing import Any

from digest.report.model import Report
from digest.report.timeutil import display


def escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", html.escape(text))


def render(report: Report) -> str:
    weekly = report.sections.get("weekly")
    synthesis = report.sections.get("conceptual", {})
    if weekly:
        synthesis = {
            "highlights": weekly["patterns"][:3],
            "projects": [
                {
                    "project_id": p["project_id"],
                    "known_now": p["progress_vs_objective"],
                    "still_unknown": [],
                    "decisions_changed": p["decisions"],
                    "no_new_conclusion": False,
                }
                for p in weekly["projects"]
            ],
        }

    plan = report.sections.get("plan")

    def claims(values: list[dict[str, Any]]) -> str:
        return "\n".join(
            escape(str(c["text"])) + " [" + ", ".join(str(e) for e in c["evidence"]) + "]"
            for c in values
        )

    lines = [
        f"# Informe {report.kind_label}",
        f"{display(report.start_at, report.timezone)} — {display(report.end_at, report.timezone)}",
        "",
        "## Lo esencial",
        claims(synthesis.get("highlights", [])) or "Síntesis pendiente.",
        "",
        "## Balance conceptual",
        "\n".join(
            "### "
            + escape(p["project_id"])
            + "\n"
            + claims(p["known_now"])
            + "\n"
            + "\n".join(escape(x) for x in p["still_unknown"])
            + "\n"
            + claims(p["decisions_changed"])
            + "\n"
            + ("No hay conclusión científica nueva." if p["no_new_conclusion"] else "")
            for p in synthesis.get("projects", [])
        )
        or "Sin balance conceptual validado.",
        "",
        "## Todo lo hecho",
    ]
    if not report.results:
        lines.append(
            "Sin resultados verificables en este intervalo. "
            "Esto no demuestra que no se haya trabajado."
        )
    for item in report.results:
        lines.extend(
            [
                f"### {escape(item.project)} · {escape(item.title)}",
                f"Tarea: {escape(item.task_id or 'fuera del tablero')} · "
                f"Revisión: {escape(item.review_label)}",
                "Evidencias: " + ", ".join(item.evidence),
            ]
        )
        extracted = report.sections.get("extract:" + item.id)
        if extracted:
            lines.extend([escape(extracted["summary"]), claims(extracted["facts"])])
            for interpretation in extracted["interpretations"]:
                lines.append(
                    "Interpretación (confianza "
                    + escape(interpretation["confidence"])
                    + "): "
                    + claims([interpretation])
                )
            lines.extend(escape(x) for x in extracted["uncertainties"])
            lines.extend(
                [
                    claims(extracted["controls_and_parameters"]),
                    claims(extracted["failures_or_blockers"]),
                ]
            )
            for number in extracted["numbers"]:
                lines.append(
                    escape(number["name"])
                    + ": "
                    + str(number["value"])
                    + " "
                    + escape(number["unit"] or "")
                    + " ["
                    + number["evidence"]
                    + "]"
                )
        for figure in item.figures:
            lines.append(f"![{escape(figure.caption)}]({figure.path}) · {figure.evidence}")
    lines.extend(
        [
            "",
            "## Propuesta de semana" if weekly else "## Plan de mañana",
            "\n".join(
                escape(item["action"])
                + " — Terminado cuando: "
                + escape(item["done_criterion"])
                + " — Dependencia: "
                + escape(item["dependency"] or "Ninguna declarada")
                + " — Motivo: "
                + escape(item["reason"])
                + " — Origen: "
                + escape(item["origin"])
                + " ["
                + ", ".join(item["evidence"])
                + "]"
                for item in (
                    weekly["next_week"]
                    if weekly
                    else [plan["mission"], *plan["warmups"]]
                    if plan
                    else []
                )
            )
            or "Sin propuesta validada.",
            "",
            "## Hilos abiertos",
        ]
    )
    lines.extend(
        escape(claim.text) + " [" + ", ".join(claim.evidence) + "]" for claim in report.open_threads
    )
    for key, extraction in report.sections.items():
        if key.startswith("extract:"):
            lines.append(claims(extraction["open_threads"]))
    if weekly:
        lines.extend(
            [
                "## Revisiones de la semana",
                "Cerradas por la persona: " + ", ".join(weekly["review_status"]["completed"]),
                "Pendientes (de mayor a menor antigüedad): "
                + ", ".join(weekly["review_status"]["pending"]),
                claims(weekly["review_status"]["doubts"]),
                "## Patrones",
                claims(weekly["patterns"]),
                "## Figuras clave",
                ", ".join(weekly["key_figures"]) or "No hay figuras disponibles.",
            ]
        )
        for project in weekly["projects"]:
            for hypothesis in project["hypotheses_changed"]:
                lines.append(
                    "Interpretación (confianza "
                    + escape(hypothesis["confidence"])
                    + "): "
                    + claims([hypothesis])
                )
    lines.extend(["", "## Nivel técnico y evidencias"])
    for entry in report.evidence:
        lines.extend(
            [
                f"### {entry.id}",
                f"{escape(entry.project)} · {escape(entry.kind)} · {escape(entry.locator)}",
                f"Hora: {display(entry.event_at or entry.observed_at, report.timezone)} "
                f"({'evento' if entry.time_quality == 'event' else 'observada'})",
                escape(entry.excerpt),
            ]
        )
    lines.extend(["", "## Cobertura"])
    for source in report.coverage:
        lines.append(
            f"- {escape(source.project)} / {source.source}: {source.status} "
            f"(captura {source.snapshot_id})"
        )
        for omission in source.omitted:
            lines.append("  - " + escape(omission["locator"]) + ": " + escape(omission["reason"]))
    lines.extend(escape(w) for w in report.warnings)
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
    if report.pending:
        lines[0] = f"# Borrador pendiente · informe {report.kind_label}"
        lines[2:2] = [
            "Generación incompleta. Sin entrega final ni cierre del intervalo.",
            "## Secciones pendientes",
            *[
                escape(key)
                + ": "
                + "; ".join(
                    escape(issue["category"] + "/" + issue["rule"] + " · " + issue["field"])
                    for issue in issues
                )
                for key, issues in sorted(report.pending.items())
            ],
        ]
    return "\n\n".join(lines) + "\n"
