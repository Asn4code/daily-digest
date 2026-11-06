"""Derive publication requirements from the inventory, never from a model flag."""

from digest.report.model import Report


def required_sections(report: Report) -> set[str]:
    required = {"extract:" + item.id for item in report.results}
    required.update(key for keys in report.source_units.values() for key in keys)
    if report.evidence or report.results:
        required.update({"weekly"} if report.kind == "weekly" else {"conceptual", "plan"})
    return required


def missing_sections(report: Report) -> set[str]:
    missing = required_sections(report) - report.sections.keys()
    # An empty ledger with failed/unavailable sources cannot prove no activity.
    if not report.evidence and (
        not report.coverage or any(c.status != "ok" for c in report.coverage)
    ):
        missing.add("capture")
    return missing


def require_complete(report: Report) -> None:
    if missing_sections(report) or report.pending or (report.evidence and report.mechanical):
        raise ValueError("Report generation is pending")
