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
        if key.startswith("critical:"):
            pid = key.split(":", 1)[1]
            if package["context"].get("project_id") != pid or value["project_id"] != pid:
                raise ValidationError("Critical project mismatch")
            expected_prior = {
                p["id"]: p
                for p in report.human_context.get("weekly_conclusions", [])
                if p["project_id"] == pid
            }
            if scope.conclusions != expected_prior:
                raise ValidationError("Prior conclusion provenance modified")
            if any(
                not set(p.get("privacy_projects", [pid])) <= scope.project_ids
                for p in scope.conclusions.values()
            ):
                raise ValidationError("Prior privacy scope narrowed")
            entries_by_id = {e.id: e for e in report.evidence}
            for prior in scope.conclusions.values():
                comparison_result = next(
                    (r for r in report.results if r.id == prior["result_id"]), None
                )
                if (
                    comparison_result is None
                    or comparison_result.project != pid
                    or not set(prior["evidence"]) <= scope.evidence.keys()
                ):
                    raise ValidationError("Prior conclusion evidence missing")
                new_ids = set(prior["new_evidence"])
                if not new_ids <= set(comparison_result.evidence) & current_evidence_ids(report):
                    raise ValidationError("New evidence outside result")
                if any(
                    (entries_by_id[eid].event_at or entries_by_id[eid].observed_at)
                    <= prior["source_date"]
                    for eid in new_ids
                ):
                    raise ValidationError("Comparison evidence is not newer")
        if key == "weekly":
            expected_critical = {
                c["conclusion_id"]: c
                for node, content in report.sections.items()
                if node.startswith("critical:")
                for c in content["checks"]
            }
            if scope.critical != expected_critical:
                raise ValidationError("Critical findings modified")
            if scope.conclusions != {
                p["id"]: p for p in report.human_context.get("weekly_conclusions", [])
            }:
                raise ValidationError("Prior conclusion provenance modified")
        parents = package.get("parents", [])
        if len(parents) != len(set(parents)) or any(
            parent not in report.sections for parent in parents
        ):
            raise ValidationError("Section dependency missing")
        if parents:
            inherited_projects = {
                pid for parent in parents for pid in report.packages[parent]["project_ids"]
            }
            if not inherited_projects <= scope.project_ids:
                raise ValidationError("Section privacy scope narrowed")
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
                or entry.locator != originals[eid].locator
                or entry.observed_at != originals[eid].observed_at
                or entry.event_at != originals[eid].event_at
                or entry.time_quality != originals[eid].time_quality
                or entry.content_hash != originals[eid].content_hash
                or entry.context_only != originals[eid].context_only
                or any(originals[eid].meta.get(k) != v for k, v in entry.meta.items())
            ):
                raise ValidationError("Section evidence modified")
        schema = SCHEMAS[key.split(":", 1)[0]]
        if not key.startswith("check:"):
            validate(schema.model_validate(value), scope)
    for key, value in report.sections.items():
        package = report.packages[key]
        if key.startswith("check:"):
            from digest.llm.grounding import check as check_grounding

            target = key.removeprefix("check:")
            if (
                target not in report.sections
                or package["context"].get("target_section") != target
                or package["context"].get("candidate") != report.sections[target]
                or package.get("parents") != [target]
                or not check_grounding(value, package).approved
                or {k: v for k, v in package.items() if k not in {"context", "parents"}}
                != {
                    k: v
                    for k, v in report.packages[target].items()
                    if k not in {"context", "parents"}
                }
                or package["context"].get("generation_context")
                != {
                    k: v
                    for k, v in report.packages[target]["context"].items()
                    if k != "validation_feedback"
                }
            ):
                raise ValidationError("Grounding binding mismatch")
        elif not key.startswith("extract:") and "check:" + key not in report.sections:
            raise ValidationError("Grounding check missing")
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
PDB_CHAIN_ID = re.compile(r"\b[0-9][A-Za-z0-9]{3}_[A-Za-z0-9]+\b")
UNIT = re.compile(
    r"^\s*((?:[%°]?(?:[^\W\d_][^\s,;:()\[\]{}<>/]*)|%)"
    r"(?:\s*/\s*[^\s,;:()\[\]{}<>/]+)*)"
)
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
    "ni",
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
    "entre",
    "sobre",
    "hasta",
    "desde",
    "tras",
    "durante",
    "sin",
    "aunque",
    "pese",
    "mientras",
    "podría",
    "podrían",
    "sugiere",
    "sugieren",
}
REFERENCE_LABEL = re.compile(
    r"\b(?:[A-Z]{2,}[A-Z0-9]*-\d+|(?i:Step|paso|proyecto|intento)\s+\d+)\b"
    r"(?![.,]\d)"
)
MONTHS = {
    month: f"{number:02d}"
    for number, month in enumerate(
        (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ),
        1,
    )
}
SPANISH_DATE = re.compile(
    r"\b(\d{1,2})\s+de\s+(" + "|".join(MONTHS) + r")\s+de(?:l)?\s+(\d{4})\b", re.I
)


COMPOUND_UNIT = re.compile(
    r"^\s+((?:(?:[YZEPTGMkhdcmuµμnpfa]?|[KMGTPEZY]i)"
    r"(?:mol|kg|byte|bit|cal|eV|cd|rad|sr|Hz|Pa|Da|m|s|g|K|A|B|L|l|J|W|N|C|V|Å)"
    r"(?:\^?[-−+]?\d+|[⁻⁺⁰¹²³⁴⁵⁶⁷⁸⁹]+)?(?=$|[\W\d_])|%|°C|°F)"
    r"[^\s,;:()\[\]{}<>/]*(?:\s*/\s*[^\s,;:()\[\]{}<>/]+)*)"
)

FILE_LABELS = {"conf", "pdb", "mmcif", "npz", "csv", "json", "png", "pdf", "svg"}
QUOTES = "\"'«»“”‘’"
UNIT_PUNCTUATION = ".!?" + QUOTES


def unit_at(text: str) -> str | None:
    text = text.lstrip().lstrip(QUOTES)
    text = re.sub(r"^de\s+(?:esas|esos|estas|estos|las|los)\s+", "", text)
    classifier = re.match(r"^(?:ficheros|archivos)\s+([^\W\d_][^\s,;:()\[\]{}<>]*)", text)
    if classifier and classifier[1].rstrip(UNIT_PUNCTUATION).casefold() in FILE_LABELS:
        # File classifiers do not change the following artifact's count label:
        # "14 ficheros conf" and "14 conf" retain the same label. Keep physical
        # suffixes and reject a different artifact or an intervening connector.
        text = text[classifier.start(1) :]
    matched = UNIT.match(text)
    if not matched or matched.group(1).rstrip(UNIT_PUNCTUATION) in CONNECTORS:
        return None
    # A slash followed by another quantity separates counts (51 structures/30
    # pairs); it is not part of a compound unit such as kcal/mol.
    parts = [re.split(r"\s*/\s*(?=\d)", matched.group(1).rstrip(UNIT_PUNCTUATION))[0]]
    if matched.group(1).rstrip(QUOTES).endswith((".", "!", "?")):
        return " ".join(parts[0].split())
    tail = text[matched.end() :]
    while (suffix := COMPOUND_UNIT.match(tail)) is not None:
        parts.append(suffix.group(1).rstrip(UNIT_PUNCTUATION))
        if suffix.group(1).rstrip(QUOTES).endswith((".", "!", "?")):
            break
        tail = tail[suffix.end() :]
    return " ".join(" ".join(parts).split())


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
    conclusions: dict[str, dict[str, Any]] = field(default_factory=dict)
    critical: dict[str, dict[str, Any]] = field(default_factory=dict)
    weekly_projects: set[str] = field(default_factory=set)
    weekly_balances: dict[str, dict[str, Any]] = field(default_factory=dict)
    has_human_context: bool = False


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
        excerpt = PDB_CHAIN_ID.sub(" ", entry.excerpt.replace("−", "-"))
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
        cited = entries(refs)
        known_structures = {
            match.group() for entry in cited for match in PDB_CHAIN_ID.finditer(entry.excerpt)
        }

        def structure(match: re.Match[str]) -> str:
            prefix = cleaned[: match.start()].rstrip()
            suffix = cleaned[match.end() :]
            for marker in ("**", "`", "*"):
                if prefix.endswith(marker) and suffix.startswith(marker):
                    prefix = prefix[: -len(marker)].rstrip()
                    suffix = suffix[len(marker) :]
            prefix = prefix.rstrip("([ \t")
            return (
                " "
                if match.group() in known_structures
                and not (prefix and (prefix[-1].isdigit() or prefix[-1] in "/^*·×+-"))
                else match.group()
            )

        cleaned = PDB_CHAIN_ID.sub(structure, cleaned)
        cleaned = re.sub(r"[`*]", "", cleaned)
        cleaned = cleaned.replace("_", "")
        for ident in sorted(
            allowed | package.result_ids | set(package.task_states), key=len, reverse=True
        ):
            cleaned = cleaned.replace(ident, "")
        known_labels = {
            " ".join(match.group().casefold().split())
            for entry in cited
            for match in REFERENCE_LABEL.finditer(entry.excerpt + " " + entry.locator)
        }

        def label(match: re.Match[str]) -> str:
            known = " ".join(match.group().casefold().split()) in known_labels
            prefix = cleaned[: match.start()].rstrip()
            # A task-like label directly after a number may be a unit. Do not
            # remove it there and accidentally permit an unsupported unit.
            return " " if known and not (prefix and prefix[-1].isdigit()) else match.group()

        cleaned = REFERENCE_LABEL.sub(label, cleaned)

        def spanish_date(match: re.Match[str]) -> str:
            dated = f"{match[3]}-{MONTHS[match[2].casefold()]}-{int(match[1]):02d}"
            if not any(
                match.group().casefold() in entry.excerpt.casefold()
                or dated in entry.excerpt
                or any(
                    stamp and stamp.startswith(dated)
                    for stamp in (entry.event_at, entry.observed_at)
                )
                for entry in cited
            ):
                raise ValidationError("unsupported_number")
            return " "

        cleaned = SPANISH_DATE.sub(spanish_date, cleaned)
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
                    "conclusion_id",
                    "critical_ids",
                    "critical_highlights",
                }:
                    continue
                if (
                    key
                    in {
                        "action",
                        "done_criterion",
                        "dependency",
                        "decision_unlocked",
                    }
                    and isinstance(item, str)
                    or ("analyses" in path and isinstance(item, str))
                ):
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
    if isinstance(output, schemas.WeeklyCritical):
        if output.project_id not in package.project_ids:
            raise ValidationError("unknown_project", ("project_id",))
        ids_checked = [check.conclusion_id for check in output.checks]
        if set(ids_checked) != package.conclusions.keys() or len(ids_checked) != len(
            set(ids_checked)
        ):
            raise ValidationError("incomplete_conclusion_checks", ("checks",))
        if (not output.checks) != (output.no_comparison_reason is not None):
            raise ValidationError("comparison_reason_missing", ("no_comparison_reason",))
        path: tuple[str | int, ...]
        for index, check in enumerate(output.checks):
            path = ("checks", index)
            prior = package.conclusions[check.conclusion_id]
            if prior["project_id"] != output.project_id:
                raise ValidationError("unknown_project", (*path, "conclusion_id"))
            old = set(prior["evidence"])
            new = set(check.new_evidence)
            if not new or not new <= set(prior["new_evidence"]) or not new <= allowed or new & old:
                raise ValidationError("new_evidence_missing", (*path, "new_evidence"))
            cited = set(check.assessment.evidence)
            if not cited & old or not cited & new:
                raise ValidationError(
                    "comparison_lineage_missing", (*path, "assessment", "evidence")
                )
            if not check.comparable and check.outcome in {"reinforces", "challenges"}:
                raise ValidationError("incomparable_conditions", (*path, "outcome"))
            if check.outcome == "challenges" and not check.alternative_explanations:
                raise ValidationError("alternatives_missing", (*path, "alternative_explanations"))
            for number, analysis in enumerate(check.analyses):
                predicted = [p.alternative_index for p in analysis.predictions]
                if set(predicted) != set(range(len(analysis.alternatives))) or len(
                    predicted
                ) != len(set(predicted)):
                    raise ValidationError(
                        "predictions_incomplete", (*path, "analyses", number, "predictions")
                    )
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
        project_ids = [p.project_id for p in output.projects]
        if (
            set(project_ids) != package.weekly_projects
            or len(project_ids) != len(set(project_ids))
            or not set(project_ids) <= package.project_ids
        ):
            raise ValidationError("unknown_project", ("projects",))
        if any(p.model_dump() != package.weekly_balances[p.project_id] for p in output.projects):
            raise ValidationError("weekly_balance_modified", ("projects",))
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
        if (
            len(output.critical_highlights) != len(set(output.critical_highlights))
            or not set(output.critical_highlights) <= package.critical.keys()
        ):
            raise ValidationError("unknown_critical_check", ("critical_highlights",))
        if (
            any(c["outcome"] != "no_material_change" for c in package.critical.values())
            and not output.critical_highlights
        ):
            raise ValidationError("critical_highlight_missing", ("critical_highlights",))
        actionable = {
            cid
            for cid, check in package.critical.items()
            if check["analyses"] or check["outcome"] in {"qualifies", "challenges"}
        }
        if actionable and not any(set(item.critical_ids) & actionable for item in output.next_week):
            raise ValidationError("critical_focus_missing", ("next_week",))
        plan = list(output.next_week)
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
        if item.origin == "review" and not package.has_human_context:
            raise ValidationError("human_review_origin_missing", (*path, "origin"))
        if isinstance(item, schemas.DailyMission | schemas.DailyWarmup | schemas.WeeklyObjective):
            if item.project_id not in package.project_ids:
                raise ValidationError("unknown_project", (*path, "project_id"))
            states = package.project_task_states.get(item.project_id, {})
        if isinstance(item, schemas.WeeklyObjective):
            if not set(item.critical_ids) <= package.critical.keys():
                raise ValidationError("unknown_critical_check", (*path, "critical_ids"))
            for cid in item.critical_ids:
                focus_prior = package.conclusions.get(cid)
                if focus_prior is None or focus_prior["project_id"] != item.project_id:
                    raise ValidationError("unknown_project", (*path, "critical_ids"))
                if not set(item.evidence) & set(package.critical[cid]["new_evidence"]):
                    raise ValidationError("critical_focus_evidence_missing", (*path, "evidence"))
        if item.origin == "kanvas":
            if item.kanvas_task_id not in states:
                raise ValidationError("unknown_kanvas_task", (*path, "kanvas_task_id"))
            if states[item.kanvas_task_id] in {"done", "review", "blocked"}:
                raise ValidationError("unavailable_kanvas_task", (*path, "kanvas_task_id"))
        elif item.kanvas_task_id is not None:
            raise ValidationError("unexpected_kanvas_task", (*path, "kanvas_task_id"))
