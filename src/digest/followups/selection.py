"""Resolve opaque selections against cited fields of an exact report revision."""

from dataclasses import dataclass
from typing import Any

from digest.collectors.base import canonical, content_hash
from digest.report.model import EvidenceEntry, Report

MAX_SELECTIONS = 8
FIELDS = {"text", "action", "done_criterion", "dependency", "reason", "summary"}


@dataclass(frozen=True)
class Selected:
    id: str
    path: tuple[str | int, ...]
    text: str
    evidence: tuple[str, ...]


def catalogue(report: Report) -> list[Selected]:
    """Enumerate exact, cited phrases; never follow a path supplied by the browser."""
    entries = {e.id for e in report.evidence}
    result: list[Selected] = []

    def walk(value: Any, path: tuple[str | int, ...]) -> None:
        if len(path) > 30 or len(result) > 10_000:
            raise ValueError("Selection inventory exceeds limits")
        if isinstance(value, dict):
            references = value.get("evidence")
            if (
                isinstance(references, list)
                and references
                and all(isinstance(e, str) and e in entries for e in references)
            ):
                for field in sorted(FIELDS & value.keys()):
                    text = value[field]
                    if isinstance(text, str) and text.strip():
                        location = (*path, field)
                        ident = (
                            "sel_"
                            + content_hash(canonical([report.id, location, text, references]))[:24]
                        )
                        result.append(Selected(ident, location, text, tuple(references)))
            for field, item in value.items():
                if isinstance(field, str) and isinstance(item, (dict, list)):
                    walk(item, (*path, field))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, (*path, index))

    walk(report.sections, ("sections",))
    for index, thread in enumerate(report.open_threads):
        walk({"text": thread.text, "evidence": thread.evidence}, ("open_threads", index))
    return result


def resolve(report: Report, identifiers: list[str]) -> tuple[list[Selected], list[EvidenceEntry]]:
    if not 1 <= len(identifiers) <= MAX_SELECTIONS or len(set(identifiers)) != len(identifiers):
        raise ValueError("Invalid phrase selection")
    choices = {item.id: item for item in catalogue(report)}
    if any(ident not in choices for ident in identifiers):
        raise ValueError("Phrase outside original report")
    selected = [choices[ident] for ident in identifiers]
    evidence_ids = {eid for item in selected for eid in item.evidence}
    return selected, [e for e in report.evidence if e.id in evidence_ids]
