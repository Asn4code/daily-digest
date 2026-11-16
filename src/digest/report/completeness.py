"""Derive publication requirements from the inventory, never from a model flag."""

from digest.report.activity import active_results
from digest.report.model import Report


def required_sections(report: Report) -> set[str]:
    active = active_results(report)
    required = {"extract:" + item.id for item in active}
    required.update(key for keys in report.source_units.values() for key in keys)
    from digest.report.monitoring import eligible, items

    required.update("watch:" + s["id"] for s in items(report) if eligible(report, s))
    from digest.report.monitoring_tree import required as required_monitoring

    required.update(required_monitoring(report))
    if active:
        if report.kind != "weekly":
            required.update("project:" + result.project for result in active)
        else:
            required.update("critical:" + result.project for result in active)
        required.update({"weekly"} if report.kind == "weekly" else {"conceptual", "plan"})
    required.update("check:" + key for key in list(required) if not key.startswith("extract:"))
    return required


def missing_sections(report: Report) -> set[str]:
    missing = required_sections(report) - report.sections.keys()
    # An empty ledger with failed/unavailable sources cannot prove no activity.
    if not active_results(report) and (
        not report.coverage or any(c.status != "ok" for c in report.coverage)
    ):
        missing.add("capture")
    return missing


def require_complete(report: Report) -> None:
    if missing_sections(report) or report.pending or (report.evidence and report.mechanical):
        raise ValueError("Report generation is pending")
