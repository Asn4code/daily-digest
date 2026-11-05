"""Mandatory reference, numeric and plan validation before publication."""

import math
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from digest.llm import schemas
from digest.report.model import EvidenceEntry, Report


class ValidationError(ValueError):
    """A report contains references outside its bounded evidence package."""


def validate_report(report: Report, allowed_ids: set[str]) -> None:
    ids = {item.id for item in report.evidence}
    if ids != allowed_ids or len(ids) != len(report.evidence):
        raise ValidationError("Report evidence package does not match its manifest")
    for result in report.results:
        if not result.evidence or not set(result.evidence) <= ids:
            raise ValidationError("Result has missing or unknown evidence")
        for figure in result.figures:
            if figure.evidence not in result.evidence:
                raise ValidationError("Figure does not belong to result evidence")
    for claim in report.open_threads:
        if not claim.evidence or not set(claim.evidence) <= ids:
            raise ValidationError("Claim has missing or unknown evidence")
    from digest.report.builder import SCHEMAS, package_scope

    if report.sections.keys() != report.packages.keys():
        raise ValidationError("Section package mismatch")
    for key, value in report.sections.items():
        package = report.packages[key]
        scope = package_scope(package)
        if not set(scope.evidence) <= ids:
            raise ValidationError("Section evidence outside report")
        originals = {item.id: item for item in report.evidence}
        for eid, entry in scope.evidence.items():
            if (
                entry.excerpt != originals[eid].excerpt
                or entry.kind != originals[eid].kind
                or entry.project != originals[eid].project
                or any(originals[eid].meta.get(k) != v for k, v in entry.meta.items())
            ):
                raise ValidationError("Section evidence modified")
        schema = SCHEMAS[key.split(":", 1)[0]]
        validate(schema.model_validate(value), scope)


# LLM output checks are independent of rendering and run again at publication.
TOKEN = re.compile(r"(?<![\w.])[-+]?(?>\d+(?:[.,]\d+)?|\.\d+)(?:[eE][-+]?\d+)?(?!\d)")
UNIT = re.compile(r"^\s*([%°]?(?:[^\W\d_][^\s,;:()\[\]{}<>]*)|%)")
CONNECTORS = {
    "en",
    "de",
    "con",
    "y",
    "a",
    "para",
    "del",
    "al",
    "el",
    "la",
    "los",
    "las",
    "que",
    "o",
    "por",
    "según",
    "donde",
    "frente",
    "vs",
    "es",
    "son",
}


COMPOUND_UNIT = re.compile(
    r"^\s+((?:[YZEPTGMkhdcmuµμnpfa]?)(?:mol|kg|cd|rad|sr|Hz|Pa|Da|m|s|g|K|A|L|l|J|W|N|C|V|Å)"
    r"(?:\^?[-−+]?\d+|[⁻⁺⁰¹²³⁴⁵⁶⁷⁸⁹]+)?)(?!\w)"
)


def unit_at(text: str) -> str | None:
    text = text.lstrip().lstrip("\"'")
    matched = UNIT.match(text)
    if not matched or matched.group(1).rstrip(".!?\"'").lower() in CONNECTORS:
        return None
    parts = [matched.group(1).rstrip(".!?\"'")]
    tail = text[matched.end() :]
    while (suffix := COMPOUND_UNIT.match(tail)) is not None:
        parts.append(suffix.group(1))
        tail = tail[suffix.end() :]
    return " ".join(parts)


@dataclass
class EvidencePackage:
    evidence: dict[str, EvidenceEntry]
    project_ids: set[str]
    result_ids: set[str] = field(default_factory=set)
    task_states: dict[str, str] = field(default_factory=dict)
    completed_reviews: set[str] = field(default_factory=set)
    pending_reviews: list[str] = field(default_factory=list)


def _numeric_values(value: Any) -> list[float]:
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numeric_values(v)]
    if isinstance(value, list):
        return [n for v in value for n in _numeric_values(v)]
    if type(value) in {int, float} and math.isfinite(value):
        return [float(value)]
    return []


def _present(number: float, unit: str | None, entries: list[EvidenceEntry]) -> bool:
    if not math.isfinite(number):
        return False
    for entry in entries:
        if unit is None and entry.kind == "metric":
            if any(
                math.isclose(number, n, rel_tol=1e-6, abs_tol=0)
                for n in _numeric_values(entry.meta.get("stats", {}))
            ):
                return True
        excerpt = entry.excerpt.replace("−", "-")
        for match in TOKEN.finditer(excerpt):
            value = float(match.group().replace(",", "."))
            if not math.isclose(number, value, rel_tol=1e-6, abs_tol=0):
                continue
            if unit is None:
                return True
            tail = excerpt[match.end() :].lstrip()
            if unit_at(tail) == " ".join(unit.split()):
                return True
    return False


def validate(output: BaseModel, package: EvidencePackage) -> None:
    """Reject unknown references, unsupported numbers, units, HTML and invalid plans."""
    allowed = set(package.evidence)

    def entries(refs: list[str]) -> list[EvidenceEntry]:
        if not refs or not set(refs) <= allowed:
            raise ValidationError("unknown_evidence")
        return [package.evidence[ident] for ident in refs]

    def text(value: str, refs: list[str], *, measurements: bool = True) -> None:
        if re.search(r"<\s*/?\s*[A-Za-z!]", value):
            raise ValidationError("html_forbidden")
        if not measurements:
            return
        # IDs may contain digits; do not mistake those references for measurements.
        cleaned = value.replace("−", "-")
        cleaned = re.sub(r"[`*_]", "", cleaned)
        for ident in sorted(
            allowed | package.result_ids | set(package.task_states), key=len, reverse=True
        ):
            cleaned = cleaned.replace(ident, "")
        for match in TOKEN.finditer(cleaned):
            unit = unit_at(cleaned[match.end() :])
            if not _present(
                float(match.group().replace(",", ".")),
                unit,
                entries(refs),
            ):
                raise ValidationError("unsupported_number")

    def visit(value: Any, inherited: list[str]) -> None:
        if isinstance(value, dict):
            refs = inherited
            if "evidence" in value:
                ref = value["evidence"]
                refs = ref if isinstance(ref, list) else [ref]
                entries(refs)
            if "value" in value and "unit" in value and "evidence" in value:
                if not _present(value["value"], value["unit"], entries(refs)):
                    raise ValidationError("unsupported_number_or_unit")
            for key, item in value.items():
                if key in {
                    "evidence",
                    "value",
                    "unit",
                    "result_id",
                    "project_id",
                    "kanvas_task_id",
                    "key_figures",
                    "completed",
                    "pending",
                }:
                    continue
                if key in {"action", "done_criterion", "dependency"} and isinstance(item, str):
                    text(item, refs, measurements=False)
                else:
                    visit(item, refs)
        elif isinstance(value, list):
            for item in value:
                visit(item, inherited)
        elif isinstance(value, str):
            text(value, inherited)

    data = output.model_dump()
    visit(data, list(allowed))
    if isinstance(output, schemas.ResultExtraction) and output.result_id not in package.result_ids:
        raise ValidationError("unknown_result")
    if isinstance(output, schemas.DailySynthesis):
        if any(p.project_id not in package.project_ids for p in output.projects):
            raise ValidationError("unknown_project")
        if output.review_candidate and output.review_candidate.result_id not in package.result_ids:
            raise ValidationError("unknown_review_candidate")
    if isinstance(output, schemas.TomorrowPlan):
        if output.mission.kind != "mission" or any(w.kind != "warmup" for w in output.warmups):
            raise ValidationError("invalid_plan_kind")
        plan = [output.mission, *output.warmups]
    elif isinstance(output, schemas.WeeklyReport):
        if any(p.project_id not in package.project_ids for p in output.projects):
            raise ValidationError("unknown_project")
        figures = {eid for eid, e in package.evidence.items() if e.kind == "figure"}
        picked = set(output.key_figures)
        if (
            len(picked) != len(output.key_figures)
            or not picked <= figures
            or len(picked) < min(4, len(figures))
        ):
            raise ValidationError("invalid_key_figures")
        if (
            set(output.review_status.completed) != package.completed_reviews
            or output.review_status.pending != package.pending_reviews
        ):
            raise ValidationError("invalid_review_summary")
        plan = output.next_week
    else:
        plan = []
    for item in plan:
        if item.origin == "kanvas":
            if item.kanvas_task_id not in package.task_states:
                raise ValidationError("unknown_kanvas_task")
            if package.task_states[item.kanvas_task_id] in {"done", "review", "blocked"}:
                raise ValidationError("unavailable_kanvas_task")
        elif item.kanvas_task_id is not None:
            raise ValidationError("unexpected_kanvas_task")
