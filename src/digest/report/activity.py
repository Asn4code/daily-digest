"""Classify the inventory before generation; failures never change its role."""

from digest.report.model import EvidenceEntry, Report, ResultEntry


def reference_evidence(report: Report, entry: EvidenceEntry) -> bool:
    return bool(
        entry.context_only
        or (entry.event_at and entry.event_at < report.start_at)
        or (
            entry.time_quality == "observed"
            and entry.meta.get("capture_origin") == "initial_inventory"
        )
    )


def current_evidence_ids(report: Report) -> set[str]:
    return {e.id for e in report.evidence if not reference_evidence(report, e)}


def reference_only(report: Report, result: ResultEntry) -> bool:
    evidence = {e.id: e for e in report.evidence}
    entries = [evidence[eid] for eid in result.evidence]
    return bool(entries) and all(reference_evidence(report, e) for e in entries)


def classify(report: Report) -> None:
    for result in report.results:
        result.reference_only = reference_only(report, result)


def active_results(report: Report) -> list[ResultEntry]:
    return [r for r in report.results if not reference_only(report, r)]
