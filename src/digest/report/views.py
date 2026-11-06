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


@dataclass(frozen=True)
class DailyView:
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
