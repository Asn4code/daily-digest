"""Bounded source-fidelity checks, separate from human comprehension."""

import json
from typing import Any

from digest.llm.schemas import GroundingAudit


def check(value: dict[str, Any], package: dict[str, Any]) -> GroundingAudit:
    audit = GroundingAudit.model_validate(value)
    if audit.approved != (not audit.issues):
        raise ValueError("grounding_inconsistent_verdict")
    entries = {e["id"]: e for e in package["evidence"]}
    for issue in audit.issues:
        if not set(issue.evidence) <= entries.keys():
            raise ValueError("grounding_unknown_reference")
        if not any(
            issue.source_quote in entries[eid]["excerpt"]
            or issue.source_quote in json.dumps(entries[eid]["meta"], ensure_ascii=False)
            for eid in issue.evidence
        ):
            raise ValueError("grounding_quote_missing")
        target = package["context"]["candidate"]
        for part in issue.field:
            if isinstance(target, dict) and isinstance(part, str) and part in target:
                target = target[part]
            elif (
                isinstance(target, list)
                and isinstance(part, int)
                and not isinstance(part, bool)
                and 0 <= part < len(target)
            ):
                target = target[part]
            else:
                raise ValueError("grounding_field_missing")
    return audit
