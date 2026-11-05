"""Render Markdown with all project-authored text escaped."""

import html
import re

from digest.report.model import Report
from digest.report.timeutil import display


def escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", html.escape(text))


def render(report: Report) -> str:
    lines = [
        f"# Informe {report.kind_label}",
        f"{display(report.start_at, report.timezone)} — {display(report.end_at, report.timezone)}",
        "",
        "## Lo esencial",
        "Informe mecánico: evidencias verificables, sin síntesis ni plan de un modelo.",
        "",
        "## Balance conceptual",
        "Sin síntesis conceptual automática en modo mecánico.",
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
        for figure in item.figures:
            lines.append(f"![{escape(figure.caption)}]({figure.path}) · {figure.evidence}")
    lines.extend(
        [
            "",
            "## Plan de mañana",
            "Sin propuesta automática en modo mecánico.",
            "",
            "## Hilos abiertos",
        ]
    )
    lines.extend(
        escape(claim.text) + " [" + ", ".join(claim.evidence) + "]" for claim in report.open_threads
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
    return "\n\n".join(lines) + "\n"
