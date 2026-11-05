"""Read notebook cells and stored outputs without executing or importing code."""

import json
from datetime import datetime
from pathlib import Path

import nbformat

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


class NotebooksCollector:
    source = "notebooks"
    phase = 2

    def collect(
        self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext
    ) -> CollectorOutput:
        names, omitted = discover(project, ctx, project.include or ["**/*.ipynb"])
        previous = (ctx.previous_payload or {}).get("files", {})
        payload = {}
        evidence = []
        budget = ctx.limits.max_project_package_chars
        for name in names:
            if Path(name).suffix.lower() != ".ipynb":
                continue
            try:
                ctx.remaining()
                omission_start = len(omitted)
                raw = read_bounded(
                    Path(project.root),
                    name,
                    exclude=project.exclude,
                    max_bytes=ctx.limits.max_file_bytes,
                )
                digest = content_hash(raw)
                if previous.get(name, {}).get("hash") == digest:
                    payload[name] = previous[name]
                    omitted.extend(Omission(**item) for item in previous[name].get("omitted", []))
                    continue
                notebook = nbformat.reads(raw.decode("utf-8"), as_version=4)  # type: ignore[no-untyped-call]
                old = previous.get(name, {}).get("cells", {})
                cells = {}
                if len(notebook.cells) > 200:
                    omitted.append(Omission(name, "notebook_cell_limit"))
                for index, cell in enumerate(notebook.cells[:200]):
                    ctx.remaining()
                    # HTML, JavaScript, binary outputs and widget state are never included.
                    outputs = []
                    for output in cell.get("outputs", []):
                        if output.get("output_type") == "stream":
                            outputs.append(str(output.get("text", "")))
                        elif output.get("output_type") == "error":
                            outputs.append(
                                str(output.get("ename", "")) + ": " + str(output.get("evalue", ""))
                            )
                        elif "text/plain" in output.get("data", {}):
                            outputs.append(str(output["data"]["text/plain"]))
                    content = {
                        "source": str(cell.get("source", "")),
                        "outputs": outputs,
                        "execution_count": cell.get("execution_count"),
                    }
                    text = canonical(content)
                    hashed = content_hash(text)
                    key = str(index)
                    cells[key] = hashed
                    if old.get(key) == hashed:
                        continue
                    if len(text) > budget:
                        omitted.append(Omission(name + "#cell/" + key, "snapshot_budget"))
                        continue
                    budget -= len(text)
                    evidence.append(
                        EvidenceDraft(
                            "notebook_change",
                            name + "#cell/" + key,
                            text,
                            (
                                "Salidas almacenadas; no demuestran ejecución en este intervalo. "
                                + text
                            )[: ctx.limits.max_excerpt_chars],
                            ctx.observed_at,
                            meta={
                                "path": name,
                                "cell": index,
                                "cell_type": cell.cell_type,
                                "execution_count": cell.get("execution_count"),
                                "stored_outputs_only": True,
                            },
                        )
                    )
                payload[name] = {
                    "hash": digest,
                    "cells": cells,
                    "omitted": [
                        {"locator": item.locator, "reason": item.reason}
                        for item in omitted[omission_start:]
                    ],
                }
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                TimeoutError,
                json.JSONDecodeError,
            ) as error:
                omitted.append(
                    Omission(
                        name, str(error) if isinstance(error, ReadError) else "notebook_unreadable"
                    )
                )
        return CollectorOutput(
            evidence, "partial" if omitted else "ok", omitted, {"files": payload}
        )
