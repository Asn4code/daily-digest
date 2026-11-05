"""Mandatory evidence-reference validation before mechanical publication."""

from digest.report.model import Report


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
