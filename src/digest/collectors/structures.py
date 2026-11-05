"""Extract structural metadata from PDB/mmCIF without loading project modules."""

import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

from digest.collectors.base import (
    CaptureContext,
    CollectorOutput,
    EvidenceDraft,
    Omission,
    canonical,
    content_hash,
)
from digest.collectors.files import discover
from digest.config import ProjectConfig
from digest.util.fs import ReadError, read_bounded


def metadata(text: str, suffix: str) -> dict[str, Any]:
    chains = set()
    residues: set[tuple[str, ...]] = set()
    header = []
    atoms = 0
    if suffix == ".pdb":
        for line in text.splitlines():
            if line.startswith(("HEADER", "TITLE ")):
                header.append(line[:80])
            if line.startswith(("ATOM  ", "HETATM")):
                if len(line) < 27:
                    raise ValueError("invalid_pdb_record")
                chains.add(line[21:22].strip() or "(sin cadena)")
                residues.add((line[21:22], line[22:27]))
                atoms += 1
    else:
        tags: list[str] = []
        active = False
        pending: list[str] = []
        for line in text.splitlines():
            value = line.strip()
            if value == "loop_":
                if pending:
                    raise ValueError("incomplete_atom_row")
                active = False
                tags = []
                continue
            if value.startswith("_atom_site."):
                tags.append(value.split()[0])
                active = True
                continue
            if not active or not value or value.startswith("#"):
                continue
            if value.startswith(("_", "data_", "stop_")):
                if pending:
                    raise ValueError("incomplete_atom_row")
                active = False
                continue
            pending.extend(shlex.split(value, comments=True, posix=True))
            while len(pending) >= len(tags):
                row = dict(zip(tags, pending[: len(tags)], strict=True))
                pending = pending[len(tags) :]
                chain = row.get("_atom_site.auth_asym_id") or row.get("_atom_site.label_asym_id")
                residue = row.get("_atom_site.auth_seq_id") or row.get("_atom_site.label_seq_id")
                if chain is None or residue is None:
                    raise ValueError("missing_atom_metadata")
                chains.add(chain)
                residues.add((chain, residue, row.get("_atom_site.pdbx_PDB_ins_code", "?")))
                atoms += 1
        if pending:
            raise ValueError("incomplete_atom_row")
    if not atoms:
        raise ValueError("no_atoms")
    return {
        "chains": sorted(chains),
        "residue_count": len(residues),
        "atom_count": atoms,
        "header": header,
    }


class StructuresCollector:
    source = "structures"
    phase = 2

    def collect(
        self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext
    ) -> CollectorOutput:
        names, omitted = discover(
            project, ctx, project.include or ["**/*.pdb", "**/*.cif", "**/*.mmcif"]
        )
        previous = (ctx.previous_payload or {}).get("files", {})
        payload = {}
        evidence = []
        for name in names:
            suffix = Path(name).suffix.lower()
            if suffix not in {".pdb", ".cif", ".mmcif"}:
                continue
            try:
                ctx.remaining()
                raw = read_bounded(
                    Path(project.root),
                    name,
                    exclude=project.exclude,
                    max_bytes=ctx.limits.max_file_bytes,
                )
                hashed = content_hash(raw)
                if previous.get(name) == hashed:
                    payload[name] = hashed
                    continue
                result = metadata(raw.decode("utf-8"), suffix)
                ctx.remaining()
                payload[name] = hashed
                evidence.append(
                    EvidenceDraft(
                        "structure",
                        name,
                        raw,
                        canonical(result)[: ctx.limits.max_excerpt_chars],
                        ctx.observed_at,
                        meta={"path": name, **result},
                    )
                )
            except (OSError, ValueError, TimeoutError) as error:
                omitted.append(
                    Omission(
                        name, str(error) if isinstance(error, ReadError) else "structure_unreadable"
                    )
                )
        return CollectorOutput(
            evidence, "partial" if omitted else "ok", omitted, {"files": payload}
        )
