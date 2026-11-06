"""Assemble validated source findings without inventing or replacing narrative."""

from typing import Any

from digest.collectors.base import canonical
from digest.llm.schemas import ResultExtraction, SourceFindings

VERSION = "1"


def assemble(result_id: str, findings: list[SourceFindings]) -> ResultExtraction:
    def unique(items: list[Any]) -> list[Any]:
        seen: set[str] = set()
        output = []
        for item in items:
            key = canonical(item)
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output

    values = [item.model_dump() for item in findings]
    # This is concatenation of validated text, not a new model interpretation.
    # Contract limits still apply; nothing is silently truncated to fit them.
    return ResultExtraction.model_validate(
        {
            "result_id": result_id,
            "summary": "\n\n".join(unique([v["summary"] for v in values])),
            "facts": unique([c for v in values for c in v["observations"]]),
            "numbers": [],
            "interpretations": unique([c for v in values for c in v["interpretations"]]),
            "uncertainties": unique([s for v in values for s in v["limitations"]]),
            "controls_and_parameters": unique([c for v in values for c in v["controls"]]),
            "failures_or_blockers": [],
            "open_threads": unique([c for v in values for c in v["open_questions"]]),
        }
    )
