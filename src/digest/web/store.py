"""Confined read-only access to validated report artifacts and their catalogue."""

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from digest.config import Config
from digest.report.loading import MAX_REPORT_BYTES, load_ready
from digest.report.model import Report
from digest.util.fs import read_bounded, safe_path

IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class Store:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.data = Path(config.paths.data_dir).resolve()
        if any(self.data.is_relative_to(Path(p.root).resolve()) for p in config.projects):
            raise ValueError("Data directory overlaps a project")

    @contextmanager
    def database(self) -> Iterator[sqlite3.Connection]:
        path = safe_path(self.data, "digest.db", max_bytes=4_000_000_000)
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        db.execute("PRAGMA query_only=ON")
        try:
            yield db
        finally:
            db.close()

    def load(self, report_id: str) -> tuple[Report, Path]:
        if not IDENTIFIER.fullmatch(report_id):
            raise ValueError("Unknown report")
        with self.database() as db:
            row = db.execute("SELECT json_path FROM report WHERE id=?", (report_id,)).fetchone()
            if not row or not isinstance(row[0], str):
                raise ValueError("Unknown report")
            relative = Path(row[0]).resolve().relative_to(self.data / "reports")
            safe_path(self.data / "reports", relative, max_bytes=MAX_REPORT_BYTES)
            report, path, _ = load_ready(db, self.config, report_id)
        return report, path

    def catalogue(self, query: str = "", page: int = 1) -> tuple[list[dict[str, Any]], bool, bool]:
        if len(query) > 200 or not 1 <= page <= 10000:
            raise ValueError("Invalid search")
        try:
            with self.database() as db:
                rows = db.execute(
                    "SELECT r.id,r.revision,r.created_at,i.kind,i.start_at,i.end_at "
                    "FROM report r JOIN interval i ON i.id=r.interval_id "
                    "WHERE r.status='ready' "
                    "ORDER BY i.end_at DESC,r.revision DESC,r.created_at DESC,r.id DESC "
                    "LIMIT ? OFFSET ?",
                    (2001 if query else 21, 0 if query else (page - 1) * 20),
                ).fetchall()
        except (OSError, ValueError, sqlite3.Error):
            return [], False, False
        truncated = bool(query and len(rows) > 2000)
        if query:
            matched = []
            for row in rows[:2000]:
                try:
                    document, _ = self.load(row[0])
                except (OSError, ValueError, sqlite3.Error):
                    continue
                sections = {
                    k: v for k, v in document.sections.items() if not k.startswith("check:")
                }
                text = json.dumps(
                    [[r.title for r in document.results], sections], ensure_ascii=False
                )
                if query.casefold() in text.casefold():
                    matched.append(row)
            rows = matched[(page - 1) * 20 : page * 20 + 1]
        entries = []
        for ident, revision, created, kind, start, end in rows[:20]:
            entries.append(
                {
                    "id": ident,
                    "revision": revision,
                    "created": created,
                    "kind": kind,
                    "start": start,
                    "end": end,
                    "label": {"daily": "Diario", "weekly": "Semanal", "preview": "Avance"}[kind],
                }
            )
        return entries, len(rows) > 20, truncated

    def select(self, kind: str, key: str | None = None) -> str | None:
        try:
            constraint = ""
            params: list[str] = [kind]
            if key is not None:
                local = (
                    datetime.strptime(key + "-1", "%G-W%V-%u")
                    if kind == "weekly"
                    else datetime.fromisoformat(key)
                ).replace(tzinfo=ZoneInfo(self.config.timezone))
                end = local + timedelta(days=7 if kind == "weekly" else 1)
                constraint = (
                    " AND julianday(i.end_at)>=julianday(?) AND julianday(i.end_at)<julianday(?)"
                )
                params.extend([local.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()])
            with self.database() as db:
                rows = db.execute(
                    "SELECT r.id,i.end_at FROM report r JOIN interval i ON i.id=r.interval_id "
                    "WHERE r.status='ready' AND i.kind=? " + constraint + " "
                    "ORDER BY i.end_at DESC,r.revision DESC LIMIT 1000",
                    params,
                ).fetchall()
        except (OSError, ValueError, sqlite3.Error):
            return None
        for ident, end in rows:
            try:
                stamp = datetime.fromisoformat(end).astimezone(ZoneInfo(self.config.timezone))
                match = stamp.strftime("%G-W%V") if kind == "weekly" else stamp.date().isoformat()
            except (ValueError, TypeError):
                continue
            if key is None or match == key:
                try:
                    self.load(ident)
                except (OSError, ValueError, sqlite3.Error):
                    continue
                return str(ident)
        return None

    def states(self, report: Report) -> dict[str, str]:
        with self.database() as db:
            return {
                result.id: str(row[0])
                if (
                    row := db.execute(
                        "SELECT review_state FROM result WHERE id=?", (result.id,)
                    ).fetchone()
                )
                else result.review_state
                for result in report.results
            }

    def figure(self, report_id: str, evidence_id: str) -> bytes:
        if not IDENTIFIER.fullmatch(evidence_id):
            raise ValueError("Unknown figure")
        report, path = self.load(report_id)
        figures = [f for r in report.results for f in r.figures if f.evidence == evidence_id]
        if not figures:
            raise ValueError("Unknown figure")
        relative = Path(figures[0].path)
        if relative.is_absolute() or not relative.parts or relative.parts[0] != "figures":
            raise ValueError("Unknown figure")
        raw = read_bounded(path.parent, relative, max_bytes=20_000_000)
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Not a generated PNG")
        return raw
