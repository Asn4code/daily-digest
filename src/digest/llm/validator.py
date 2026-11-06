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

    def __init__(self, rule: str, path: tuple[str | int, ...] = ()) -> None:
        super().__init__(rule)
        self.path = path


def validate_report(report: Report, allowed_ids: set[str]) -> None:
    from digest.report.assembly import assemble
    from digest.report.observations import normalize

    ids = {item.id for item in report.evidence}
    if ids != allowed_ids or len(ids) != len(report.evidence):
        raise ValidationError("Report evidence package does not match its manifest")
    for item in report.evidence:
        if "report_role" in item.meta:
            expected_role = (
                "historical_reference"
                if item.event_at and item.event_at < report.start_at
                else "interval_evidence"
            )
            if item.meta["report_role"] != expected_role:
                raise ValidationError("Evidence temporal role mismatch")
    if (report.observations or report.source_units) and report.observations != {
        e.id: normalize(e) for e in report.evidence
    }:
        raise ValidationError("Normalized observation modified")
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
        if any(e.project not in scope.project_ids for e in scope.evidence.values()):
            raise ValidationError("Section project scope mismatch")
        if not set(scope.evidence) <= ids:
            raise ValidationError("Section evidence outside report")
        originals = {item.id: item for item in report.evidence}
        for eid, entry in scope.evidence.items():
            if (
                entry.excerpt != originals[eid].excerpt
                or entry.kind != originals[eid].kind
                or entry.project != originals[eid].project
                or entry.content_hash != originals[eid].content_hash
                or any(originals[eid].meta.get(k) != v for k, v in entry.meta.items())
            ):
                raise ValidationError("Section evidence modified")
        schema = SCHEMAS[key.split(":", 1)[0]]
        validate(schema.model_validate(value), scope)
    for result in report.results:
        root = "extract:" + result.id
        if root in report.sections and result.id in report.source_units:
            children = report.source_units[result.id]
            if (
                not children
                or len(children) != len(set(children))
                or any(not key.startswith("source:" + result.id + ":") for key in children)
                or any(key not in report.sections for key in children)
                or report.packages[root]["context"].get("assembled_from") != children
            ):
                raise ValidationError("Source assembly incomplete")
            expected = assemble(
                result.id,
                [schemas.SourceFindings.model_validate(report.sections[key]) for key in children],
            )
            if report.sections[root] != expected.model_dump():
                raise ValidationError("Source assembly modified")
            package = report.packages[root]
            if set(e["id"] for e in package["evidence"]) != set(result.evidence):
                raise ValidationError("Result assembly evidence incomplete")
            if set(e["id"] for key in children for e in report.packages[key]["evidence"]) != set(
                result.evidence
            ):
                raise ValidationError("Source packet evidence incomplete")


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
                for n in _numeric_values(
                    [entry.meta.get("stats", {}), entry.meta.get("change", {})]
                )
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

    def visit(value: Any, inherited: list[str], path: tuple[str | int, ...] = ()) -> None:
        try:
            visit_value(value, inherited, path)
        except ValidationError as error:
            if not error.path:
                error.path = path
            raise

    def visit_value(value: Any, inherited: list[str], path: tuple[str | int, ...]) -> None:
        if isinstance(value, dict):
            refs = inherited
            if "evidence" in value:
                ref = value["evidence"]
                refs = ref if isinstance(ref, list) else [ref]
                try:
                    entries(refs)
                except ValidationError as error:
                    error.path = (*path, "evidence")
                    raise
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
                    try:
                        text(item, refs, measurements=False)
                    except ValidationError as error:
                        error.path = (*path, key)
                        raise
                else:
                    visit(item, refs, (*path, key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, inherited, (*path, index))
        elif isinstance(value, str):
            text(value, inherited)

    data = output.model_dump()
    visit(data, list(allowed))
    if (
        isinstance(output, schemas.ResultExtraction | schemas.SourceFindings)
        and output.result_id not in package.result_ids
    ):
        raise ValidationError("unknown_result", ("result_id",))
    if isinstance(output, schemas.DailySynthesis):
        if any(p.project_id not in package.project_ids for p in output.projects):
            raise ValidationError("unknown_project", ("projects",))
        if output.review_candidate and output.review_candidate.result_id not in package.result_ids:
            raise ValidationError("unknown_review_candidate", ("review_candidate", "result_id"))
    if isinstance(output, schemas.TomorrowPlan):
        if output.mission.kind != "mission" or any(w.kind != "warmup" for w in output.warmups):
            raise ValidationError("invalid_plan_kind", ("mission", "kind"))
        plan = [output.mission, *output.warmups]
    elif isinstance(output, schemas.WeeklyReport):
        if any(p.project_id not in package.project_ids for p in output.projects):
            raise ValidationError("unknown_project", ("projects",))
        figures = {eid for eid, e in package.evidence.items() if e.kind == "figure"}
        picked = set(output.key_figures)
        if (
            len(picked) != len(output.key_figures)
            or not picked <= figures
            or len(picked) < min(4, len(figures))
        ):
            raise ValidationError("invalid_key_figures", ("key_figures",))
        if (
            set(output.review_status.completed) != package.completed_reviews
            or output.review_status.pending != package.pending_reviews
        ):
            raise ValidationError("invalid_review_summary", ("review_status",))
        plan = output.next_week
    else:
        plan = []
    for index, item in enumerate(plan):
        path = (
            ("next_week", index)
            if isinstance(output, schemas.WeeklyReport)
            else ("mission",)
            if index == 0
            else ("warmups", index - 1)
        )
        if item.origin == "kanvas":
            if item.kanvas_task_id not in package.task_states:
                raise ValidationError("unknown_kanvas_task", (*path, "kanvas_task_id"))
            if package.task_states[item.kanvas_task_id] in {"done", "review", "blocked"}:
                raise ValidationError("unavailable_kanvas_task", (*path, "kanvas_task_id"))
        elif item.kanvas_task_id is not None:
            raise ValidationError("unexpected_kanvas_task", (*path, "kanvas_task_id"))
