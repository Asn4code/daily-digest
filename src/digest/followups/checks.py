"""Deterministic, bounded checks; a source declaration is never an experiment."""

import csv
import io
import math
import statistics
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Any

from digest.collectors.base import content_hash, utc
from digest.collectors.files import matches
from digest.collectors.metrics import records
from digest.config import Config
from digest.report.model import EvidenceEntry
from digest.util.fs import ReadError, read_bounded
from digest.util.redact import known_secrets, redact_tree

METHOD = "metric_summary_v1"
MAX_ROWS = 10_000
MAX_BYTES = 256_000
STATISTICS = {"n", "mean", "median", "min", "max"}


def metric_summary(config: Config, entry: EvidenceEntry, *, now: datetime) -> dict[str, Any]:
    """Recompute configured summary fields, keeping historical and current hashes distinct."""
    result: dict[str, Any] = {
        "method": METHOD,
        "checked_at": utc(now),
        "source_evidence": entry.id,
        "historical_hash": entry.content_hash,
        "current_hash": None,
        "status": "not_verifiable",
        "reason": "unsupported_source",
        "computed": {},
        "mismatches": [],
        "invalid_rows": {},
        "limits": ["Solo verifica los estadísticos registrados; no la validez del experimento."],
    }

    def clean() -> dict[str, Any]:
        value = redact_tree(result, known_secrets(config))
        assert isinstance(value, dict)
        return value

    def unavailable(reason: str) -> dict[str, Any]:
        result["reason"] = reason
        return clean()

    project = next((p for p in config.projects if p.id == entry.project), None)
    if project is None or entry.kind != "metric":
        return clean()
    name, original = entry.meta.get("path"), entry.meta.get("stats")
    if not isinstance(name, str) or not isinstance(original, dict) or not original:
        return unavailable("missing_metric_metadata")
    allowed = {
        column
        for metric in project.metrics
        if matches(name, [metric.pattern])
        for column in metric.columns
    }
    if len(original) > 20 or not set(original) <= allowed:
        return unavailable("metric_configuration_changed")
    if not entry.content_hash:
        return unavailable("historical_hash_missing")
    if any(
        not isinstance(values, dict)
        or set(values) != STATISTICS
        or any(type(v) not in {int, float} or not math.isfinite(v) for v in values.values())
        for values in original.values()
    ):
        return unavailable("invalid_historical_statistics")
    try:
        raw = read_bounded(
            Path(project.root),
            name,
            exclude=project.exclude,
            max_bytes=min(MAX_BYTES, config.limits.max_file_bytes),
        )
        result["current_hash"] = content_hash(raw)
        suffix = Path(name).suffix.lower()
        if suffix in {".csv", ".tsv"}:
            reader = csv.DictReader(
                io.StringIO(raw.decode("utf-8-sig")), delimiter="\t" if suffix == ".tsv" else ","
            )
            rows = list(islice(reader, MAX_ROWS + 1))
        else:
            rows = records(raw, suffix)
        if len(rows) > MAX_ROWS:
            return unavailable("row_budget_exceeded")
        for column, expected in original.items():
            valid, invalid = [], 0
            for row in rows:
                value = row.get(column)
                try:
                    if value is None or isinstance(value, bool):
                        raise ValueError("Not numeric")
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError("Not finite")
                    valid.append(number)
                except (ValueError, TypeError, OverflowError):
                    invalid += 1
            if not valid:
                return unavailable("numeric_data_missing")
            ordered = sorted(valid)
            middle = len(ordered) // 2
            actual = {
                "n": len(valid),
                "mean": statistics.mean(valid),
                "median": ordered[middle]
                if len(ordered) % 2
                else ordered[middle - 1] / 2 + ordered[middle] / 2,
                "min": min(valid),
                "max": max(valid),
            }
            if any(not math.isfinite(v) for v in actual.values()):
                return unavailable("nonfinite_statistics")
            result["computed"][column] = actual
            result["invalid_rows"][column] = invalid
            for statistic, value in actual.items():
                # The same deterministic method and bytes must reproduce the stored
                # float exactly; an absolute epsilon can hide errors at small scales.
                if value != expected[statistic]:
                    result["mismatches"].append(
                        {
                            "column": column,
                            "statistic": statistic,
                            "historical": expected[statistic],
                            "computed": value,
                        }
                    )
    except ReadError as error:
        return unavailable(str(error))
    except (ValueError, UnicodeError, csv.Error, OverflowError):
        return unavailable("invalid_numeric_data")
    if result["current_hash"] != entry.content_hash:
        result.update(status="changed_data", reason="current_data_differs_from_original")
        result["limits"].append(
            "Los datos actuales no son los del informe; "
            "no invalida por sí solo el cálculo histórico."
        )
    elif result["mismatches"]:
        result.update(status="discrepancy", reason="stored_statistics_not_reproduced")
    else:
        result.update(status="reproduced", reason="stored_statistics_reproduced")
    if any(result["invalid_rows"].values()):
        result["limits"].append(
            "Estadísticos solo de filas numéricas válidas; se indican las filas omitidas."
        )
    return clean()
