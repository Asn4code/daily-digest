"""Revalidate complete persisted reports before closing or delivering them."""

import sqlite3
from pathlib import Path

from pydantic import TypeAdapter

from digest.config import Config
from digest.llm.validator import validate_report
from digest.report.completeness import require_complete
from digest.report.model import Report
from digest.util.fs import read_bounded

MAX_REPORT_BYTES = 100_000_000


def load_ready(db: sqlite3.Connection, config: Config, report_id: str) -> tuple[Report, Path, int]:
    row = db.execute(
        "SELECT r.json_path,r.status,i.kind,i.start_at,i.end_at,i.id "
        "FROM report r JOIN interval i ON i.id=r.interval_id WHERE r.id=?",
        (report_id,),
    ).fetchone()
    if not row or row[1] != "ready":
        raise ValueError("Report is not deliverable")
    if not isinstance(row[0], str):
        raise ValueError("Report artifact missing")
    data = Path(config.paths.data_dir).resolve()
    path = Path(row[0]).resolve()
    if not path.is_relative_to(data) or any(
        path.is_relative_to(Path(p.root).resolve()) for p in config.projects
    ):
        raise ValueError("Report outside service data")
    raw = read_bounded(data, path.relative_to(data), max_bytes=MAX_REPORT_BYTES)
    report = TypeAdapter(Report).validate_json(raw)
    if (report.id, report.kind, report.start_at, report.end_at) != (
        report_id,
        row[2],
        row[3],
        row[4],
    ):
        raise ValueError("Report identity or window changed")
    manifest = {
        r[0]
        for r in db.execute(
            "SELECT evidence_id FROM report_evidence WHERE report_id=?", (report_id,)
        )
    }
    validate_report(report, manifest)
    require_complete(report)
    return report, path, row[5]
