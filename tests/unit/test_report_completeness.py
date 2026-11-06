"""Pending generation cannot masquerade as a complete or empty report."""

import pytest

from digest.report.completeness import missing_sections, require_complete
from digest.report.model import Coverage, EvidenceEntry, Report, ResultEntry


@pytest.mark.parametrize(
    "kind,required",
    [
        ("daily", {"conceptual", "plan"}),
        ("preview", {"conceptual", "plan"}),
        ("weekly", {"weekly"}),
    ],
)
def test_requirements_come_from_inventory_not_mechanical_flag(
    kind: str, required: set[str]
) -> None:
    report = Report("r", kind, "start", "end", "now", mechanical=False)
    report.evidence = [
        EvidenceEntry("ev", "p", "doc_change", "note", "Control", "now", None, "observed", {})
    ]
    report.results = [ResultEntry("res", "p", "Result", None, "pending", ["ev"])]
    assert missing_sections(report) == {"extract:res", *required}
    report.sections = {key: {} for key in required}
    with pytest.raises(ValueError, match="generation is pending"):
        require_complete(report)


def test_empty_report_with_missing_or_failed_coverage_stays_pending() -> None:
    report = Report("r", "daily", "start", "end", "now", mechanical=False)
    assert missing_sections(report) == {"capture"}
    report.coverage = [Coverage(1, "p", "git", "failed", [])]
    assert missing_sections(report) == {"capture"}
    with pytest.raises(ValueError, match="generation is pending"):
        require_complete(report)
    report.coverage[0].status = "ok"
    assert not missing_sections(report)
    require_complete(report)
