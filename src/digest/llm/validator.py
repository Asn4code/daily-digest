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
    from digest.report.activity import reference_only
    from digest.report.assembly import assemble
    from digest.report.observations import normalize

    ids = {item.id for item in report.evidence}
    if ids != allowed_ids or len(ids) != len(report.evidence):
        raise ValidationError("Report evidence package does not match its manifest")
    for item in report.evidence:
        if "report_role" in item.meta:
            expected_role = (
                "supporting_context"
                if item.context_only
                else "historical_reference"
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
        if result.reference_only != reference_only(report, result):
            raise ValidationError("Result activity role mismatch")
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
        from digest.report.activity import current_evidence_ids

        eligible = set(scope.evidence)
        if package.get("wire_mode") == "references":
            eligible &= current_evidence_ids(report)
        expected_results = {
            r.id: set(r.evidence) & eligible for r in report.results if r.id in scope.result_ids
        }
        if scope.result_evidence != expected_results:
            raise ValidationError("Result evidence index modified")
        parents = package.get("parents", [])
        if len(parents) != len(set(parents)) or any(
            parent not in report.sections for parent in parents
        ):
            raise ValidationError("Section dependency missing")
        if parents:
            inherited = {e["id"] for parent in parents for e in report.packages[parent]["evidence"]}
            auxiliary = set(package.get("auxiliary_evidence", []))
            reference = set(package.get("reference_evidence", []))
            if not auxiliary | reference <= set(scope.evidence):
                raise ValidationError("Context evidence outside section")
            originals_by_id = {e.id: e for e in report.evidence}
            if any(originals_by_id[eid].kind != "task_transition" for eid in auxiliary):
                raise ValidationError("Invalid workflow context")
            if not set(scope.evidence) <= inherited | auxiliary | reference:
                raise ValidationError("Section lineage incomplete")
        originals = {item.id: item for item in report.evidence}
        for eid, entry in scope.evidence.items():
            if (
                entry.excerpt != originals[eid].excerpt
                or entry.kind != originals[eid].kind
                or entry.project != originals[eid].project
                or entry.content_hash != originals[eid].content_hash
                or entry.context_only != originals[eid].context_only
                or any(originals[eid].meta.get(k) != v for k, v in entry.meta.items())
            ):
                raise ValidationError("Section evidence modified")
        schema = SCHEMAS[key.split(":", 1)[0]]
        validate(schema.model_validate(value), scope)
    for result in report.results:
        root = "extract:" + result.id
        if root in report.sections and result.id not in report.source_units:
            raise ValidationError("Source manifest missing")
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
    "se",
    "usado",
    "usados",
    "usada",
    "usadas",
}


COMPOUND_UNIT = re.compile(
    r"^\s+((?:[YZEPTGMkhdcmuµμnpfa]?)(?:mol|kg|cd|rad|sr|Hz|Pa|Da|m|s|g|K|A|L|l|J|W|N|C|V|Å)"
    r"(?:\^?[-−+]?\d+|[⁻⁺⁰¹²³⁴⁵⁶⁷⁸⁹]+)?)(?!\w)"
)


def unit_at(text: str) -> str | None:
    text = text.lstrip().lstrip("\"'")
    text = re.sub(r"^de\s+(?:esas|esos|estas|estos|las|los)\s+", "", text)
    matched = UNIT.match(text)
    if not matched or matched.group(1).rstrip(".!?\"'") in CONNECTORS:
        return None
    # A slash followed by another quantity separates counts (51 structures/30
    # pairs); it is not part of a compound unit such as kcal/mol.
    parts = [re.split(r"/(?=\d)", matched.group(1).rstrip(".!?\"'"))[0]]
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
    result_projects: dict[str, str] = field(default_factory=dict)
    closed_results: set[str] = field(default_factory=set)
    human_plan_ids: set[int] = field(default_factory=set)
    active_plan_id: int | None = None
    project_task_states: dict[str, dict[str, str]] = field(default_factory=dict)
    result_evidence: dict[str, set[str]] = field(default_factory=dict)


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
        # Dates are also provenance: a note's event date need not be repeated
        # literally in its excerpt. Keep exact cited dates, never infer one.
        for dated in re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", cleaned):
            if not any(
                dated in entry.excerpt
                or any(
                    stamp and stamp.startswith(dated)
                    for stamp in (entry.event_at, entry.observed_at)
                )
                for entry in entries(refs)
            ):
                raise ValidationError("unsupported_number")
            cleaned = cleaned.replace(dated, "")
        for clock in re.findall(r"(?<!\d)\d{2}:\d{2}(?::\d{2})?(?!\d)", cleaned):
            if not any(
                clock in entry.excerpt
                or any(
                    stamp
                    and len(stamp) >= 19
                    and stamp[10] == "T"
                    and stamp[11 : 11 + len(clock)] == clock
                    for stamp in (entry.event_at, entry.observed_at)
                )
                for entry in entries(refs)
            ):
                raise ValidationError("unsupported_number")
            cleaned = cleaned.replace(clock, "")
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
                    "result_ids",
                    "carry_forward_id",
                    "human_plan_id",
                }:
                    continue
                if key in {
                    "action",
                    "done_criterion",
                    "dependency",
                    "decision_unlocked",
                } and isinstance(item, str):
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
        isinstance(output, schemas.ResultExtraction | schemas.SourceFindings | schemas.ResultFiche)
        and output.result_id not in package.result_ids
    ):
        raise ValidationError("unknown_result", ("result_id",))
    if isinstance(output, schemas.ResultFiche) and any(
        s.result_id != output.result_id for s in output.sources
    ):
        raise ValidationError("source_result_mismatch", ("sources",))
    if isinstance(output, schemas.DailySynthesis):
        if any(p.project_id not in package.project_ids for p in output.projects):
            raise ValidationError("unknown_project", ("projects",))
        if output.review_candidate and output.review_candidate.result_id not in package.result_ids:
            raise ValidationError("unknown_review_candidate", ("review_candidate", "result_id"))
    if isinstance(output, schemas.ProjectDigest):
        if package.project_ids != {output.project_id}:
            raise ValidationError("unknown_project", ("project_id",))
        results = [r.result_id for r in output.results]
        if set(results) != package.result_ids or len(results) != len(set(results)):
            raise ValidationError("incomplete_result_explanations", ("results",))
        for index, card in enumerate(output.results):
            cited = {eid for claim in card.observations for eid in claim.evidence}
            if not cited & package.result_evidence.get(card.result_id, set()):
                raise ValidationError(
                    "result_observation_missing", ("results", index, "observations")
                )
    if isinstance(output, schemas.DailyOverview):
        for index, highlight in enumerate(output.highlights):
            if highlight.project_id not in package.project_ids:
                raise ValidationError("unknown_project", ("highlights", index, "project_id"))
            if not set(highlight.result_ids) <= package.result_ids or any(
                package.result_projects.get(rid) != highlight.project_id
                for rid in highlight.result_ids
            ):
                raise ValidationError("unknown_result", ("highlights", index, "result_ids"))
            cited = set(highlight.observation.evidence)
            if not any(
                cited & package.result_evidence.get(rid, set()) for rid in highlight.result_ids
            ):
                raise ValidationError(
                    "result_observation_missing", ("highlights", index, "observation")
                )
        candidate = output.review_candidate
        if candidate and (
            candidate.result_id not in package.result_ids
            or candidate.result_id in package.closed_results
        ):
            raise ValidationError("unavailable_review_candidate", ("review_candidate", "result_id"))
    plan: list[schemas.PlanItem]
    if isinstance(output, schemas.TomorrowPlan):
        if (output.mission and output.mission.kind != "mission") or any(
            w.kind != "warmup" for w in output.warmups
        ):
            raise ValidationError("invalid_plan_kind", ("mission", "kind"))
        if (
            sum(
                [
                    output.mission is not None,
                    output.carry_forward_id is not None,
                    output.no_mission_reason is not None,
                ]
            )
            != 1
        ):
            raise ValidationError("invalid_plan_choice", ("mission",))
        if (
            output.carry_forward_id is not None
            and output.carry_forward_id != package.active_plan_id
        ):
            raise ValidationError("unknown_human_plan", ("carry_forward_id",))
        mission = output.mission
        if mission:
            if package.human_plan_ids and output.change_reason is None:
                raise ValidationError("accepted_plan_change_unjustified", ("change_reason",))
            if (
                mission.human_plan_id is not None
                and mission.human_plan_id not in package.human_plan_ids
            ):
                raise ValidationError("unknown_human_plan", ("mission", "human_plan_id"))
            if len(mission.priority_basis) != len(set(mission.priority_basis)):
                raise ValidationError("duplicate_priority_basis", ("mission", "priority_basis"))
            if "human_commitment" in mission.priority_basis and mission.human_plan_id is None:
                raise ValidationError("human_commitment_missing", ("mission", "human_plan_id"))
            if "control" in mission.priority_basis and mission.uncertainty_addressed is None:
                raise ValidationError(
                    "control_reason_missing", ("mission", "uncertainty_addressed")
                )
            if "decision" in mission.priority_basis and mission.decision_unlocked is None:
                raise ValidationError("decision_reason_missing", ("mission", "decision_unlocked"))
            if "dependency" in mission.priority_basis and mission.dependency is None:
                raise ValidationError("dependency_reason_missing", ("mission", "dependency"))
            if "kanvas" in mission.priority_basis and mission.origin != "kanvas":
                raise ValidationError("kanvas_reason_missing", ("mission", "origin"))
        plan = [*([mission] if mission else []), *output.warmups]
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
            if index == 0 and isinstance(output, schemas.TomorrowPlan) and output.mission
            else (
                "warmups",
                index
                - int(isinstance(output, schemas.TomorrowPlan) and output.mission is not None),
            )
        )
        states = package.task_states
        if isinstance(item, schemas.DailyMission | schemas.DailyWarmup):
            if item.project_id not in package.project_ids:
                raise ValidationError("unknown_project", (*path, "project_id"))
            states = package.project_task_states.get(item.project_id, {})
        if item.origin == "kanvas":
            if item.kanvas_task_id not in states:
                raise ValidationError("unknown_kanvas_task", (*path, "kanvas_task_id"))
            if states[item.kanvas_task_id] in {"done", "review", "blocked"}:
                raise ValidationError("unavailable_kanvas_task", (*path, "kanvas_task_id"))
        elif item.kanvas_task_id is not None:
            raise ValidationError("unexpected_kanvas_task", (*path, "kanvas_task_id"))
