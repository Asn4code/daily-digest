"""Shared channel values: presentation changes, scientific meaning does not."""

from dataclasses import dataclass
from typing import Any

from digest.report.model import Report

PRIORITIES = {
    "scientific_value": "valor científico",
    "decision": "decisión que desbloquea",
    "control": "control o duda pendiente",
    "dependency": "dependencia",
    "human_commitment": "compromiso humano",
    "kanvas": "tarea de Kanvas",
}
CONFIDENCE = {"low": "baja", "medium": "media", "high": "alta"}
OUTCOMES = {
    "reinforces": "Refuerza",
    "qualifies": "Matiza o restringe",
    "challenges": "Pone en duda",
    "inconclusive": "No permite decidir",
    "no_material_change": "Sin cambio material",
}


def weekly_checks(report: Report, *, highlighted: bool = False) -> list[dict[str, Any]]:
    prior = {p["id"]: p for p in report.human_context.get("weekly_conclusions", [])}
    checks = {
        c["conclusion_id"]: c
        for key, value in report.sections.items()
        if key.startswith("critical:")
        for c in value["checks"]
    }
    selected = (
        report.sections.get("weekly", {}).get("critical_highlights", []) if highlighted else checks
    )
    return [
        {**checks[cid], "prior": prior[cid], "label": OUTCOMES[checks[cid]["outcome"]]}
        for cid in selected
    ]


def weekly_notices(report: Report) -> list[dict[str, Any]]:
    return [
        value["no_comparison_reason"]
        for key, value in report.sections.items()
        if key.startswith("critical:") and value["no_comparison_reason"]
    ]


@dataclass(frozen=True)
class DailyView:
    orientation_notice: str
    highlights: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    cards: dict[str, dict[str, Any]]
    mission: dict[str, Any] | None
    warmups: list[dict[str, Any]]
    accepted: dict[str, Any] | None
    carry_forward: bool
    no_mission_reason: dict[str, Any] | None
    change_reason: dict[str, Any] | None
    planning_for: str | None


def daily_view(report: Report) -> DailyView:
    projects = [
        value for key, value in sorted(report.sections.items()) if key.startswith("project:")
    ]
    plan = report.sections.get("plan", {})
    accepted = report.human_context.get("accepted_plan")
    carry = plan.get("carry_forward_id") is not None or (
        not plan and accepted is not None and accepted["availability"] == "available"
    )
    return DailyView(
        "Hay resultados del intervalo, sin novedades destacadas en esta orientación."
        if any(not r.reference_only for r in report.results)
        else (
            "Sin novedades verificadas del intervalo; "
            "la referencia inicial o histórica está en el inventario."
        ),
        report.sections.get("conceptual", {}).get("highlights", []),
        projects,
        {card["result_id"]: card for project in projects for card in project["results"]},
        plan.get("mission"),
        plan.get("warmups", []),
        accepted,
        carry,
        plan.get("no_mission_reason"),
        plan.get("change_reason"),
        report.human_context.get("planning_for"),
    )
