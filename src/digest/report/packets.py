"""Pack linked source units whole; never split a comparison to fit a prompt."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from digest.collectors.base import canonical, content_hash
from digest.report.model import EvidenceEntry

SOURCE_PACKET_CHARS = 24_000
SCIENTIFIC = {"metric", "figure", "notebook_change", "structure", "run", "run_error"}


@dataclass(frozen=True)
class Packet:
    key: str
    evidence: list[str]
    units: list[list[str]]
    fits: bool


def units(entries: list[EvidenceEntry]) -> tuple[list[list[str]], list[str]]:
    """Use artifact identity, experiment directory and explicit path references.

    Ambiguous task notes are shared context, not a licence to discard controls.
    A linked unit that is too big remains pending instead of being cut by bytes.
    """
    if len({e.project for e in entries}) > 1:
        raise ValueError("Source units require a single project")
    by_id = {e.id: e for e in entries}
    parent = {e.id: e.id for e in entries}

    def root(ident: str) -> str:
        while parent[ident] != ident:
            parent[ident] = parent[parent[ident]]
            ident = parent[ident]
        return ident

    def join(left: str, right: str) -> None:
        parent[root(left)] = root(right)

    paths: dict[str, list[str]] = {}
    directories: dict[str, list[str]] = {}
    anchors = []
    for e in entries:
        path = e.meta.get("path")
        if isinstance(path, str):
            paths.setdefault(path, []).append(e.id)
            directory = str(PurePosixPath(path).parent)
            # Group technical changes too: small files do not imply a model call each.
            family = "experiment" if e.kind in SCIENTIFIC else e.kind
            if e.kind in SCIENTIFIC or e.kind in {"diff", "uncommitted"}:
                directories.setdefault(family + ":" + directory, []).append(e.id)
        elif e.kind.startswith("task_") or e.kind == "commit":
            anchors.append(e.id)
    for related in [*paths.values(), *directories.values()]:
        for ident in related[1:]:
            join(related[0], ident)
    references = (
        re.compile(
            r"(?<![\w./-])(?:"
            + "|".join(re.escape(path) for path in sorted(paths, key=len, reverse=True))
            + r")(?![\w/-]|\.[\w./-])"
        )
        if paths
        else None
    )
    for e in entries:
        referenced = (
            [eid for match in references.finditer(e.excerpt) for eid in paths[match.group()]]
            if references
            else []
        )
        for ident in referenced:
            join(e.id, ident)
        if referenced and e.id in anchors:
            anchors.remove(e.id)
    groups: dict[str, list[str]] = {}
    for ident in sorted(by_id):
        if ident not in anchors:
            groups.setdefault(root(ident), []).append(ident)
    return sorted(groups.values(), key=lambda group: group[0]), sorted(anchors)


def plan(
    entries: list[EvidenceEntry], *, size: Callable[[list[str]], int], limit: int
) -> list[Packet]:
    coherent, anchors = units(entries)
    if not coherent and anchors:
        coherent = [anchors]
        anchors = []
    packed: list[Packet] = []
    current: list[list[str]] = []

    def emit(groups: list[list[str]]) -> None:
        ids = sorted({*anchors, *(eid for group in groups for eid in group)})
        packed.append(Packet(content_hash(canonical(ids))[:12], ids, groups, size(ids) <= limit))

    for group in coherent:
        combined = sorted({*anchors, *(eid for unit in [*current, group] for eid in unit)})
        if current and size(combined) > limit:
            emit(current)
            current = []
        current.append(group)
        if size(sorted({*anchors, *group})) > limit:
            emit(current)
            current = []
    if current:
        emit(current)
    return packed
