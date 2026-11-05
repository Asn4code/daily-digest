"""One locked worker processes queued capture and report jobs."""

import fcntl
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from digest.capture import capture, validate_data_directory
from digest.collectors.base import canonical, utc
from digest.config import Config
from digest.db import connect
from digest.intervals import close_interval, open_interval, pending_days
from digest.llm.validator import validate_report
from digest.report.mechanical import build
from digest.report.render_html import render as render_html
from digest.report.render_md import render as render_md
from digest.util.fs import read_bounded


def enqueue(
    config: Config, kind: str, *, requested_by: str = "cli", params: dict[str, Any] | None = None
) -> int:
    data = validate_data_directory(config)
    data.mkdir(parents=True, exist_ok=True)
    with closing(connect(data / "digest.db")) as db:
        cursor = db.execute(
            "INSERT INTO job(kind,params,requested_by,state,created_at) VALUES (?,?,?,?,?)",
            (kind, canonical(params or {}), requested_by, "queued", utc(datetime.now(UTC))),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid


@contextmanager
def lock(config: Config) -> Iterator[sqlite3.Connection]:
    data = validate_data_directory(config)
    data.mkdir(parents=True, exist_ok=True)
    with (data / "worker.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        with closing(connect(data / "digest.db")) as db:
            yield db


def _instant(value: str | None) -> datetime | None:
    if value is None:
        return None
    date = datetime.fromisoformat(value)
    utc(date)
    return date


def execute(
    config: Config, job_id: int | None = None, *, now: datetime | None = None
) -> str | None:
    with lock(config) as db:
        instant = now or datetime.now(UTC)
        row = db.execute(
            "SELECT id,kind,params,requested_by FROM job WHERE state='queued' "
            + ("AND id=? " if job_id else "")
            + "ORDER BY id LIMIT 1",
            (job_id,) if job_id else (),
        ).fetchone()
        if not row:
            return None
        ident, kind, encoded, requested_by = row
        params = json.loads(encoded)
        db.execute("UPDATE job SET state='running',started_at=? WHERE id=?", (utc(instant), ident))
        report_id: str | None = None
        try:
            capture(db, config, now=instant, project_id=params.get("project"))
            if kind == "capture":
                db.execute(
                    "UPDATE job SET state='done',finished_at=? WHERE id=?",
                    (utc(datetime.now(UTC)), ident),
                )
                return "capture"
            if kind not in {"daily", "preview", "weekly"}:
                raise ValueError("Unsupported job")
            since = _instant(params.get("since"))
            until = _instant(params.get("until"))
            if until and until > instant:
                raise ValueError("Future interval")
            # Explicitly repeated bounds refer to a revision of the same interval.
            existing = (
                db.execute(
                    "SELECT id,closed FROM interval WHERE kind=? AND start_at=? AND end_at=? "
                    "ORDER BY id DESC LIMIT 1",
                    (kind, utc(since), utc(until)),
                ).fetchone()
                if since and until
                else None
            )
            interval = open_interval(
                db,
                instant,
                kind=kind,
                requested_by=requested_by,
                timezone=config.timezone,
                since=since,
                until=until,
            )
            if interval is None:
                db.execute(
                    "UPDATE job SET state='skipped',finished_at=? WHERE id=?",
                    (utc(datetime.now(UTC)), ident),
                )
                return "skipped"
            if existing:
                db.execute("DELETE FROM interval WHERE id=?", (interval.id,))
                from digest.intervals import Interval

                interval = Interval(existing[0], kind, interval.start, interval.end)
            date = interval.end.astimezone(ZoneInfo(config.timezone))
            stamp = date.strftime("%G-W%V") if kind == "weekly" else date.strftime("%Y-%m-%d")
            prefix = f"rep_{kind}_{stamp}_r"
            revisions = [
                int(r[0].rsplit("_r", 1)[1])
                for r in db.execute("SELECT id FROM report WHERE id LIKE ?", (prefix + "%",))
            ]
            revision = max(revisions, default=0) + 1
            report_id = prefix + str(revision)
            directory = Path(config.paths.data_dir) / "reports" / kind / report_id
            db.execute(
                "INSERT INTO report(id,interval_id,revision,status,created_at) VALUES "
                "(?,?,?,'generating',?)",
                (report_id, interval.id, revision, utc(instant)),
            )
            report = build(db, interval, report_id, instant, regenerate=bool(existing))
            report.timezone = config.timezone
            validate_report(report, {item.id for item in report.evidence})
            directory.mkdir(parents=True, exist_ok=False)
            for result in report.results:
                for figure in result.figures:
                    original = Path(figure.path).resolve()
                    data = Path(config.paths.data_dir).resolve()
                    if not original.is_relative_to(data) or original.suffix != ".png":
                        raise ValueError("Invalid thumbnail path")
                    raw = read_bounded(
                        data, original.relative_to(data), max_bytes=config.limits.max_file_bytes * 4
                    )
                    images = directory / "figures"
                    images.mkdir(exist_ok=True)
                    target = images / original.name
                    if not target.exists():
                        with target.open("xb") as stream:
                            stream.write(raw)
                    figure.path = "figures/" + original.name
            for name, text in [
                ("report.json", json.dumps(asdict(report), ensure_ascii=False, indent=2)),
                ("report.md", render_md(report)),
                ("report.html", render_html(report)),
            ]:
                with (directory / name).open("x", encoding="utf-8") as stream:
                    stream.write(text)
            db.execute(
                "UPDATE report SET "
                "status='mechanical',json_path=?,md_path=?,html_path=?,coverage=? WHERE id=?",
                (
                    str(directory / "report.json"),
                    str(directory / "report.md"),
                    str(directory / "report.html"),
                    canonical([asdict(item) for item in report.coverage]),
                    report_id,
                ),
            )
            db.executemany(
                "INSERT INTO report_evidence VALUES (?,?)",
                [(report_id, item.id) for item in report.evidence],
            )
            close_interval(db, interval.id, report_id)
            params["report_id"] = report_id
            db.execute(
                "UPDATE job SET state='done',finished_at=?,params=? WHERE id=?",
                (utc(datetime.now(UTC)), canonical(params), ident),
            )
            return str(directory / "report.md")
        except Exception:
            if report_id is not None:
                db.execute(
                    "UPDATE report SET status='failed' WHERE id=? AND status='generating'",
                    (report_id,),
                )
            db.execute(
                "UPDATE job SET state='failed',finished_at=?,error='job_failed' WHERE id=?",
                (utc(datetime.now(UTC)), ident),
            )
            raise RuntimeError("El trabajo falló; consulta el registro y la cobertura.") from None


def recover(config: Config) -> int:
    with lock(config) as db:
        db.execute(
            "UPDATE job SET state='failed',error='worker_interrupted',finished_at=? "
            "WHERE state='running'",
            (utc(datetime.now(UTC)),),
        )
        db.execute("UPDATE report SET status='failed' WHERE status='generating'")
        days = pending_days(db, datetime.now(UTC), timezone=config.timezone)
    count = 0
    for start, end in days:
        params = {"since": utc(start), "until": utc(end)}
        with lock(config) as db:
            existing = db.execute(
                "SELECT 1 FROM job WHERE kind='daily' AND params=? AND state IN "
                "('queued','running')",
                (canonical(params),),
            ).fetchone()
        if not existing:
            enqueue(config, "daily", requested_by="timer", params=params)
            count += 1
    return count
