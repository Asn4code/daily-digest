"""Compute declared numeric summaries, never model-derived measurements."""

import csv
import io
import json
import math
import statistics
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


def records(raw: bytes, suffix: str) -> list[dict[str, Any]]:
    text = raw.decode("utf-8-sig")
    if suffix == ".json":
        value = json.loads(text)
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise ValueError("invalid_metric_json")
        return value
    if suffix not in {".csv", ".tsv"}:
        raise ValueError("unsupported_metric_format")
    return list(csv.DictReader(io.StringIO(text), delimiter="\t" if suffix == ".tsv" else ","))


class MetricsCollector:
    source = "metrics"
    phase = 1

    def collect(
        self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext
    ) -> CollectorOutput:
        previous = (ctx.previous_payload or {}).get("files", {})
        payload = {}
        omitted = []
        evidence = []
        for index, metric in enumerate(project.metrics):
            files, errors = discover(project, ctx, [metric.pattern])
            omitted.extend(errors)
            if not files:
                omitted.append(Omission(metric.pattern, "metric_no_match"))
            for name in files:
                key = f"{index}:{name}"
                try:
                    ctx.remaining()
                    raw = read_bounded(
                        Path(project.root),
                        name,
                        exclude=project.exclude,
                        max_bytes=ctx.limits.max_file_bytes,
                    )
                    hashed = content_hash(raw)
                    old = previous.get(key, {})
                    if old.get("hash") == hashed:
                        payload[key] = old
                        continue
                    rows = records(raw, Path(name).suffix.lower())
                    stats = {}
                    changes: dict[str, dict[str, float]] = {}
                    for column in metric.columns:
                        ctx.remaining()
                        values = []
                        bad = 0
                        if not rows or not any(column in row for row in rows):
                            omitted.append(Omission(name + "#" + column, "missing_column"))
                            continue
                        for row in rows:
                            value = row.get(column)
                            try:
                                if isinstance(value, bool) or value is None:
                                    raise ValueError
                                number = float(value)
                                if not math.isfinite(number):
                                    raise ValueError
                                values.append(number)
                            except (TypeError, ValueError, OverflowError):
                                bad += 1
                        if bad:
                            omitted.append(Omission(name + "#" + column, "invalid_numeric_values"))
                        if not values:
                            continue
                        ordered = sorted(values)
                        middle = len(ordered) // 2
                        median = (
                            ordered[middle]
                            if len(ordered) % 2
                            else ordered[middle - 1] / 2 + ordered[middle] / 2
                        )
                        summary = {
                            "n": len(values),
                            "mean": statistics.mean(values),
                            "median": median,
                            "min": min(values),
                            "max": max(values),
                        }
                        stats[column] = summary
                        before = old.get("stats", {}).get(column, {})
                        changes[column] = {}
                        for label, value in summary.items():
                            if label not in before or label == "n":
                                continue
                            delta = float(value) - float(before[label])
                            if math.isfinite(delta):
                                changes[column][label] = delta
                            else:
                                omitted.append(Omission(name + "#" + column, "nonfinite_change"))
                    if not stats:
                        continue
                    payload[key] = {"hash": hashed, "stats": stats}
                    content = {
                        "label": metric.label,
                        "path": name,
                        "stats": stats,
                        "change": changes,
                    }
                    evidence.append(
                        EvidenceDraft(
                            "metric",
                            key,
                            raw,
                            canonical(content)[: ctx.limits.max_excerpt_chars],
                            ctx.observed_at,
                            meta=content,
                        )
                    )
                except (OSError, ValueError, TimeoutError, csv.Error) as error:
                    reason = str(error) if isinstance(error, ReadError) else "metric_unreadable"
                    if reason != "excluded":
                        omitted.append(Omission(name, reason))
        return CollectorOutput(
            evidence, "partial" if omitted else "ok", omitted, {"files": payload}
        )
