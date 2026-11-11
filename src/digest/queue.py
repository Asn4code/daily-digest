"""Short queue transactions shared by web, CLI and timers; no worker work here."""

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from digest.capture import validate_data_directory
from digest.collectors.base import canonical, content_hash, utc
from digest.config import Config
from digest.db import connect
from digest.util.fs import safe_path

REPORT_KINDS = {"daily", "weekly", "preview"}


@contextmanager
def writing(config: Config) -> Iterator[sqlite3.Connection]:
    data = validate_data_directory(config)
    data.mkdir(parents=True, exist_ok=True)
    path = data / "digest.db"
    if path.exists() or path.is_symlink():
        path = safe_path(data, "digest.db", max_bytes=4_000_000_000)
    if any(path.resolve().is_relative_to(Path(p.root).resolve()) for p in config.projects):
        raise ValueError("Database overlaps a project")
    db = connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def request_key(kind: str, params: dict[str, Any], requested_by: str) -> str | None:
    if kind not in REPORT_KINDS or params.get("since") or params.get("until"):
        return None
    if set(params) - {"since", "until", "no_send", "request_key"}:
        return None
    return content_hash(
        canonical(
            {
                "kind": kind,
                "no_send": kind == "preview" or bool(params.get("no_send")),
                # Timer weeks end on Saturday; manual weeks end at the current midnight.
                "window": "scheduled"
                if kind == "weekly" and requested_by == "timer"
                else "current",
            }
        )
    )


def insert(db: sqlite3.Connection, kind: str, params: dict[str, Any], requested_by: str) -> int:
    value = dict(params)
    key = request_key(kind, value, requested_by)
    if key is not None:
        existing = db.execute(
            "SELECT id FROM job WHERE kind=? AND state IN ('queued','running') "
            "AND json_extract(params,'$.request_key')=? ORDER BY id LIMIT 1",
            (kind, key),
        ).fetchone()
        if existing:
            return int(existing[0])
        value["request_key"] = key
    cursor = db.execute(
        "INSERT INTO job(kind,params,requested_by,state,created_at) VALUES (?,?,?,'queued',?)",
        (kind, canonical(value), requested_by, utc(datetime.now(UTC))),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def submission(db: sqlite3.Connection, ident: str, request: dict[str, Any]) -> int | None:
    if not re.fullmatch(r"[a-f0-9]{32}", ident):
        raise ValueError("Invalid submission")
    row = db.execute(
        "SELECT value FROM meta WHERE key=?", ("queue_submission:" + ident,)
    ).fetchone()
    if row:
        prior = json.loads(row[0])
        if prior["request"] != request:
            raise ValueError("Submission already used")
        return int(prior["job"])
    return None


def remember(db: sqlite3.Connection, ident: str, request: dict[str, Any], job: int) -> int:
    db.execute(
        "INSERT INTO meta(key,value) VALUES (?,?)",
        (
            "queue_submission:" + ident,
            canonical({"request": request, "job": job}),
        ),
    )
    return job


def generate(db: sqlite3.Connection, kind: str, ident: str) -> int:
    if kind not in REPORT_KINDS:
        raise ValueError("Unknown report kind")
    request = {"kind": kind}
    prior = submission(db, ident, request)
    if prior is not None:
        return prior
    job = insert(db, kind, {"no_send": kind == "preview"}, "web")
    return remember(db, ident, request, job)


def retry_delivery(db: sqlite3.Connection, delivery_id: int, ident: str) -> int:
    request = {"delivery": delivery_id}
    prior = submission(db, ident, request)
    if prior is not None:
        return prior
    row = db.execute(
        "SELECT report_id,review_id,channel,state FROM delivery WHERE id=?", (delivery_id,)
    ).fetchone()
    if not row or row[3] not in {"pending", "failed"}:
        raise ValueError("Delivery is not retryable")
    report, review, channel, _ = row
    if not report and not review:
        raise ValueError("Delivery has no target")
    params = (
        {"review": review, "channel": channel} if review else {"report": report, "channel": channel}
    )
    existing = db.execute(
        "SELECT id FROM job WHERE kind='deliver' AND state IN ('queued','running') "
        "AND json_extract(params,?)=? AND (json_extract(params,'$.channel') IS NULL "
        "OR json_extract(params,'$.channel')=?) ORDER BY id LIMIT 1",
        ("$.review" if review else "$.report", review or report, channel),
    ).fetchone()
    job = int(existing[0]) if existing else insert(db, "deliver", params, "web")
    return remember(db, ident, request, job)


def resume(db: sqlite3.Connection, job_id: int, ident: str) -> int:
    request = {"resume": job_id}
    prior = submission(db, ident, request)
    if prior is not None:
        return prior
    row = db.execute("SELECT kind,state,params FROM job WHERE id=?", (job_id,)).fetchone()
    if not row or row[0] not in REPORT_KINDS:
        raise ValueError("Unknown report job")
    if row[1] in {"queued", "running"}:
        return remember(db, ident, request, job_id)
    params = json.loads(row[2])
    if row[1] != "failed" or not params.get("interval_id"):
        raise ValueError("Job has no resumable interval")
    ready = db.execute(
        "SELECT 1 FROM report WHERE interval_id=? AND status='ready' AND revision>?",
        (params["interval_id"], int(params.get("revision_after", 0))),
    ).fetchone()
    if ready:
        raise ValueError("Job superseded by a complete report")
    params["attempts"] = 0
    db.execute(
        "UPDATE job SET state='queued',params=?,error=NULL,finished_at=NULL WHERE id=?",
        (canonical(params), job_id),
    )
    return remember(db, ident, request, job_id)


def retry_plan(
    db: sqlite3.Connection, config: Config, plan_id: str, channel: str, ident: str
) -> int:
    from digest.planning import meta, snapshot

    if channel not in {"obsidian", "drive"}:
        raise ValueError("Unknown plan channel")
    request = {"plan": plan_id, "channel": channel}
    prior = submission(db, ident, request)
    if prior is not None:
        return prior
    snapshot(db, config, plan_id)
    state = meta(db, f"plan_delivery:{plan_id}:{channel}", {"state": "pending"})
    if state["state"] not in {"pending", "failed"}:
        raise ValueError("Plan delivery not retryable")
    existing = db.execute(
        "SELECT id FROM job WHERE kind='deliver' AND state IN ('queued','running') "
        "AND json_extract(params,'$.plan')=? AND (json_extract(params,'$.channel') IS NULL "
        "OR json_extract(params,'$.channel')=?) ORDER BY id LIMIT 1",
        (plan_id, channel),
    ).fetchone()
    job = int(existing[0]) if existing else insert(db, "deliver", request, "web")
    return remember(db, ident, request, job)
