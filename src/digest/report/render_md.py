"""Render Markdown with all project-authored text escaped."""

import html
import re
from typing import Any

from digest.report.model import Report
from digest.report.timeutil import display


def escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", html.escape(text))


def render(report: Report) -> str:
    synthesis = report.sections.get("conceptual", {})
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
        claims(synthesis.get("highlights", []))
        or "Informe mecánico: evidencias verificables, sin síntesis ni plan de un modelo.",
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
        or "Sin síntesis conceptual automática en modo mecánico.",
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
            "## Plan de mañana",
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
                for item in ([plan["mission"], *plan["warmups"]] if plan else [])
            )
            or "Sin propuesta automática en modo mecánico.",
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
    return "\n\n".join(lines) + "\n"
