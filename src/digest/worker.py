"""One locked worker processes queued capture and report jobs."""

import fcntl
import json
import sqlite3
import time
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
from digest.report import inventory
from digest.report.completeness import missing_sections, require_complete
from digest.report.loading import load_ready
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
        from digest.review.notes import import_ready

        import_ready(db, config)
        instant = now or datetime.now(UTC)
        deadline = time.monotonic() + config.schedule.max_generation_minutes * 60
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
            if kind == "contrast":
                from digest.llm.router import Router
                from digest.review.contrast import execute as contrast_review

                contrast_review(
                    db,
                    config,
                    params["review"],
                    Router(db, config, job_id=ident, deadline=deadline),
                )
                db.execute(
                    "UPDATE job SET state='done',finished_at=? WHERE id=?",
                    (utc(datetime.now(UTC)), ident),
                )
                return str(params["review"])
            if kind == "deliver":
                from digest.publish.deliveries import deliver_report, retry

                if params.get("plan"):
                    from digest.publish.plan import publish as publish_plan

                    outcomes = {str(params["plan"]): publish_plan(db, config, params["plan"])}
                elif params.get("review"):
                    from digest.review.notes import publish as publish_review

                    outcomes = {str(params["review"]): publish_review(db, config, params["review"])}
                elif params.get("report"):
                    outcomes = {
                        params["report"]: deliver_report(
                            db,
                            config,
                            params["report"],
                            channel=params.get("channel"),
                            force_uncertain=bool(params.get("force_uncertain")),
                        )
                    }
                else:
                    outcomes = retry(
                        db,
                        config,
                        channel=params.get("channel"),
                        force_uncertain=bool(params.get("force_uncertain")),
                    )
                db.execute(
                    "UPDATE job SET state='done',finished_at=? WHERE id=?",
                    (utc(datetime.now(UTC)), ident),
                )
                return canonical(outcomes)
            params["attempts"] = int(params.get("attempts", 0)) + 1
            db.execute("UPDATE job SET params=? WHERE id=?", (canonical(params), ident))
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
            previous_report = params.get("report_id")
            if previous_report:
                db.execute(
                    "UPDATE report SET status='failed' WHERE id=? AND status='generating'",
                    (previous_report,),
                )
            params.update(
                since=utc(interval.start), until=utc(interval.end), interval_id=interval.id
            )
            if "revision_after" not in params:
                params["revision_after"] = db.execute(
                    "SELECT COALESCE(max(revision),0) FROM report "
                    "WHERE interval_id=? AND status='ready'",
                    (interval.id,),
                ).fetchone()[0]
            db.execute("UPDATE job SET params=? WHERE id=?", (canonical(params), ident))
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
            params["report_id"] = report_id
            db.execute("UPDATE job SET params=? WHERE id=?", (canonical(params), ident))
            if params.get("inventory_hash"):
                report = inventory.load(config, ident, params["inventory_hash"])
            else:
                report = build(db, interval, report_id, instant, regenerate=bool(existing))
                validate_report(report, {item.id for item in report.evidence})
                report, frozen_path, frozen_hash = inventory.save(config, ident, report)
                params.update(inventory_path=frozen_path, inventory_hash=frozen_hash)
                db.execute("UPDATE job SET params=? WHERE id=?", (canonical(params), ident))
            if (report.kind, report.start_at, report.end_at) != (
                kind,
                utc(interval.start),
                utc(interval.end),
            ):
                raise ValueError("Frozen inventory window mismatch")
            report.id = report_id
            report.created_at = utc(instant)
            report.timezone = config.timezone
            # Freeze evidence, not a person's later understanding of that evidence.
            for result in report.results:
                state = db.execute(
                    "SELECT review_state FROM result WHERE id=?", (result.id,)
                ).fetchone()
                if state:
                    result.review_state = state[0]
            db.executemany(
                "INSERT OR IGNORE INTO report_evidence VALUES (?,?)",
                [(report_id, item.id) for item in report.evidence],
            )
            from digest.llm.router import Router
            from digest.report.builder import enrich

            enrich(db, config, report, Router(db, config, job_id=ident, deadline=deadline))
            params.update(
                json.loads(db.execute("SELECT params FROM job WHERE id=?", (ident,)).fetchone()[0])
            )
            db.executemany(
                "INSERT OR IGNORE INTO report_evidence VALUES (?,?)",
                [(report_id, item.id) for item in report.evidence],
            )
            validate_report(report, {item.id for item in report.evidence})
            for key in missing_sections(report):
                report.pending.setdefault(
                    key,
                    [
                        {
                            "category": "input",
                            "rule": "section_missing",
                            "field": "$",
                            "section": key,
                        }
                    ],
                )
            pending = bool(report.pending)
            basename = "draft" if pending else "report"
            if pending:
                directory = Path(config.paths.data_dir) / "drafts" / kind / report_id
            else:
                require_complete(report)
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
                (basename + ".json", json.dumps(asdict(report), ensure_ascii=False, indent=2)),
                (basename + ".md", render_md(report)),
                (basename + ".html", render_html(report)),
            ]:
                with (directory / name).open("x", encoding="utf-8") as stream:
                    stream.write(text)
            db.execute(
                "UPDATE report SET "
                "status=?,json_path=?,md_path=?,html_path=?,coverage=?,"
                "model_info=?,prompt_versions=? WHERE id=?",
                (
                    "generating" if pending else "ready",
                    str(directory / (basename + ".json")),
                    str(directory / (basename + ".md")),
                    str(directory / (basename + ".html")),
                    canonical([asdict(item) for item in report.coverage]),
                    canonical(report.model_info),
                    canonical(report.prompt_versions),
                    report_id,
                ),
            )
            if pending:
                params.update(report_id=report_id, draft_path=str(directory / "draft.md"))
                db.execute(
                    "UPDATE job SET state='failed',finished_at=?,error='report_pending',params=? "
                    "WHERE id=?",
                    (utc(datetime.now(UTC)), canonical(params), ident),
                )
                return str(directory / "draft.md")
            if "plan" in report.sections:
                proposal = report.sections["plan"]
                items = ([proposal["mission"]] if proposal["mission"] else []) + proposal["warmups"]
                for item in items:
                    inserted = db.execute(
                        "INSERT INTO plan_item(report_id,kind,action,done_criterion,dependency,"
                        "reason,origin,kanvas_task_id) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            report_id,
                            item["kind"],
                            item["action"],
                            item["done_criterion"],
                            item["dependency"],
                            item["reason"],
                            item["origin"],
                            item["kanvas_task_id"],
                        ),
                    )
                    assert inserted.lastrowid is not None
                    db.execute(
                        "INSERT INTO meta(key,value) VALUES (?,?)",
                        (f"plan_project:{inserted.lastrowid}", item["project_id"]),
                    )
                    db.execute(
                        "INSERT INTO meta(key,value) VALUES (?,?)",
                        (
                            f"plan_scope:{inserted.lastrowid}",
                            canonical(report.packages["plan"]["project_ids"]),
                        ),
                    )
            close_interval(db, interval.id, report_id)
            if kind != "preview" and not params.get("no_send"):
                from digest.publish.deliveries import deliver_report

                params["deliveries"] = deliver_report(db, config, report_id)
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


def resume(config: Config, job_id: int, *, no_send: bool = False) -> None:
    with lock(config) as db:
        row = db.execute("SELECT kind,state,params FROM job WHERE id=?", (job_id,)).fetchone()
        if not row or row[0] not in {"daily", "weekly", "preview"} or row[1] != "failed":
            raise ValueError("Only a failed report job can be resumed")
        params = json.loads(row[2])
        previous = db.execute(
            "SELECT r.status,i.id,i.start_at,i.end_at,i.closed FROM report r "
            "JOIN interval i ON i.id=r.interval_id WHERE r.id=?",
            (params.get("report_id"),),
        ).fetchone()
        latest_ready = db.execute(
            "SELECT COALESCE(max(revision),0) FROM report WHERE interval_id=? AND status='ready'",
            (previous[1] if previous else params.get("interval_id"),),
        ).fetchone()[0]
        if previous and (
            previous[0] in {"ready", "mechanical"}
            or latest_ready > int(params.get("revision_after", 0))
        ):
            raise ValueError("Report is already finalized")
        if previous and not params.get("interval_id"):
            params.update(interval_id=previous[1], since=previous[2], until=previous[3])
        if not params.get("interval_id"):
            raise ValueError("Job has no frozen report window")
        params["attempts"] = 0
        if no_send:
            params["no_send"] = True
        db.execute(
            "UPDATE job SET state='queued',error=NULL,finished_at=NULL,params=? WHERE id=?",
            (canonical(params), job_id),
        )


def recover(config: Config) -> int:
    count = 0
    with lock(config) as db:
        db.execute(
            "UPDATE job SET state='failed',error='worker_interrupted',finished_at=? "
            "WHERE state='running'",
            (utc(datetime.now(UTC)),),
        )
        for job_id, encoded in db.execute(
            "SELECT id,params FROM job WHERE kind IN ('daily','weekly','preview') "
            "AND state='failed' AND error IN ('worker_interrupted','report_pending') ORDER BY id"
        ).fetchall():
            params = json.loads(encoded)
            if not params.get("interval_id"):
                continue
            final = db.execute(
                "SELECT status FROM report WHERE id=?", (params.get("report_id"),)
            ).fetchone()
            if final and final[0] == "ready":
                try:
                    ready, _, interval_id = load_ready(db, config, params["report_id"])
                    close_interval(db, interval_id, ready.id)
                except (ValueError, OSError):
                    db.execute(
                        "UPDATE report SET status='failed' WHERE id=?", (params["report_id"],)
                    )
                    db.execute(
                        "UPDATE job SET error='report_validation_failed' WHERE id=?", (job_id,)
                    )
                    continue
                if ready.kind != "preview" and not params.get("no_send"):
                    states = dict(
                        db.execute(
                            "SELECT channel,state FROM delivery WHERE report_id=?", (ready.id,)
                        )
                    )
                    actionable = any(
                        states.get(channel) not in {"sent", "uncertain"}
                        for channel in ("obsidian", "drive", "email")
                    )
                    queued = db.execute(
                        "SELECT 1 FROM job WHERE kind='deliver' AND state IN ('queued','running') "
                        "AND json_extract(params,'$.report')=?",
                        (ready.id,),
                    ).fetchone()
                    if actionable and not queued:
                        db.execute(
                            "INSERT INTO job(kind,params,requested_by,state,created_at) "
                            "VALUES ('deliver',?,'timer','queued',?)",
                            (canonical({"report": ready.id}), utc(datetime.now(UTC))),
                        )
                        count += 1
                db.execute("UPDATE job SET state='done',error=NULL WHERE id=?", (job_id,))
            elif db.execute(
                "SELECT 1 FROM report WHERE interval_id=? AND status='ready' "
                "AND revision>? LIMIT 1",
                (params["interval_id"], int(params.get("revision_after", 0))),
            ).fetchone():
                db.execute(
                    "UPDATE job SET state='skipped',error='superseded_by_ready_report' WHERE id=?",
                    (job_id,),
                )
            elif int(params.get("attempts", 0)) < 3:
                db.execute(
                    "UPDATE job SET state='queued',error=NULL,finished_at=NULL WHERE id=?",
                    (job_id,),
                )
                count += 1
        db.execute(
            "UPDATE report SET status='failed' WHERE status='generating' "
            "AND NOT EXISTS (SELECT 1 FROM job WHERE "
            "(error='report_pending' OR state='queued') "
            "AND json_extract(params,'$.report_id')=report.id)"
        )
        days = pending_days(db, datetime.now(UTC), timezone=config.timezone)
    for start, end in days:
        params = {"since": utc(start), "until": utc(end)}
        with lock(config) as db:
            existing = db.execute(
                "SELECT 1 FROM job WHERE kind='daily' AND state IN ('queued','running') "
                "AND json_extract(params,'$.since')=? AND json_extract(params,'$.until')=?",
                (utc(start), utc(end)),
            ).fetchone()
        if not existing:
            enqueue(config, "daily", requested_by="timer", params=params)
            count += 1
    return count
