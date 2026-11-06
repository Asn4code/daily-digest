"""Freeze a private, sanitized inventory before starting report generation."""

import json
from dataclasses import asdict
from pathlib import Path

from pydantic import TypeAdapter

from digest.collectors.base import canonical, content_hash
from digest.config import Config
from digest.publish.files import create, destination
from digest.report.model import Report
from digest.util.fs import read_bounded
from digest.util.redact import known_secrets, redact_tree

MAX_INVENTORY_BYTES = 100_000_000
VERSION = "1"


def decode(raw: bytes) -> Report:
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "report"}
        or value["version"] != VERSION
    ):
        raise ValueError("Unsupported inventory format")
    return TypeAdapter(Report).validate_python(value["report"])


def save(config: Config, job_id: int, report: Report) -> tuple[Report, str, str]:
    data = Path(config.paths.data_dir).resolve()
    relative = f"work/jobs/{job_id}/inventory.json"
    path = destination(config, data, relative)
    # Recover an atomic file whose database reference was interrupted before commit.
    if path.exists():
        raw = read_bounded(data, relative, max_bytes=MAX_INVENTORY_BYTES)
        frozen = decode(raw)
        if (frozen.kind, frozen.start_at, frozen.end_at) != (
            report.kind,
            report.start_at,
            report.end_at,
        ):
            raise ValueError("Frozen inventory window mismatch")
        return frozen, str(path), content_hash(raw)
    value = redact_tree(asdict(report), known_secrets(config))
    sanitized = TypeAdapter(Report).validate_python(value)
    raw = canonical({"version": VERSION, "report": value}).encode()
    if len(raw) > MAX_INVENTORY_BYTES:
        raise ValueError("Inventory exceeds storage limit")
    create(path, raw)
    return sanitized, str(path), content_hash(raw)


def load(config: Config, job_id: int, expected_hash: str) -> Report:
    data = Path(config.paths.data_dir).resolve()
    relative = f"work/jobs/{job_id}/inventory.json"
    raw = read_bounded(data, relative, max_bytes=MAX_INVENTORY_BYTES)
    if content_hash(raw) != expected_hash:
        raise ValueError("Frozen inventory changed")
    return decode(raw)
