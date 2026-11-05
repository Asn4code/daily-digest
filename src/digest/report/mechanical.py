"""Build complete evidence-grounded mechanical reports from the registry."""

import json
import sqlite3
from datetime import datetime

from digest.collectors.base import canonical, content_hash, utc
from digest.collectors.store import previous_payload
from digest.intervals import Interval
from digest.report.model import Claim, Coverage, EvidenceEntry, Figure, Report, ResultEntry


def build(
    db: sqlite3.Connection,
    interval: Interval,
    ident: str,
    now: datetime,
    *,
    regenerate: bool = False,
) -> Report:
    sql = (
        "SELECT "
        "e.id,e.project_id,e.kind,e.locator,e.excerpt,"
        "e.observed_at,e.event_at,e.time_quality,e.meta "
        "FROM evidence e WHERE COALESCE(e.event_at,e.observed_at)>=? "
        "AND COALESCE(e.event_at,e.observed_at)<=?"
    )
    if interval.kind != "weekly" and not regenerate:
        sql += (
            " AND NOT EXISTS(SELECT 1 FROM report_evidence re JOIN report r ON re.report_id=r.id "
            "JOIN interval i ON r.interval_id=i.id WHERE re.evidence_id=e.id AND i.kind='daily' "
            "AND i.closed=1 AND r.status IN ('mechanical','ready'))"
        )
    rows = db.execute(
        sql + " ORDER BY e.project_id,e.observed_at,e.id", (utc(interval.start), utc(interval.end))
    ).fetchall()
    items = [
        EvidenceEntry(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], json.loads(r[8]))
        for r in rows
    ]
    ids = {item.id for item in items}
    report = Report(
        ident, interval.kind, utc(interval.start), utc(interval.end), utc(now), evidence=items
    )
    for row in db.execute(
        "SELECT id,project_id,title,task_id,review_state FROM result ORDER BY "
        "project_id,first_seen_at,id"
    ):
        result_id, project, title, task, state = row
        references = [
            r[0]
            for r in db.execute(
                "SELECT evidence_id FROM result_evidence WHERE result_id=? ORDER BY evidence_id",
                (result_id,),
            )
            if r[0] in ids
        ]
        if not references:
            continue
        figures = [
            Figure(item.id, item.meta["thumbnail"], "Figura capturada: " + item.locator)
            for item in items
            if item.id in references and item.kind == "figure" and "thumbnail" in item.meta
        ]
        report.results.append(
            ResultEntry(result_id, project, title, task, state, references, figures)
        )
    # Only current pending questions/states are open; old transitions remain technical evidence.
    tasks = {}
    for row in db.execute(
        "SELECT project_id,task_id,kind,excerpt,meta,id FROM evidence WHERE task_id "
        "IS NOT NULL ORDER BY observed_at,snapshot_id,rowid"
    ):
        tasks[(row[0], row[1])] = row
    for row in tasks.values():
        _, _, kind, excerpt, metadata, eid = row
        meta = json.loads(metadata)
        if eid in ids and (kind == "task_question" or meta.get("state") == "doing"):
            report.open_threads.append(Claim(excerpt, [eid]))
    for item in items:
        if item.kind != "uncommitted":
            continue
        payload = previous_payload(db, item.project, "git") or {}
        row = db.execute("SELECT content_hash FROM evidence WHERE id=?", (item.id,)).fetchone()
        key = content_hash(canonical([item.kind, item.locator, row[0]]))
        if key in payload.get("seen", []):
            report.open_threads.append(Claim(item.excerpt, [item.id]))
    snapshots = db.execute(
        "SELECT s.id,s.project_id,s.source,s.status,s.error FROM snapshot s "
        "WHERE s.id=(SELECT max(t.id) FROM snapshot t WHERE "
        "t.project_id=s.project_id AND t.source=s.source) "
        "ORDER BY s.project_id,s.source"
    ).fetchall()
    report.coverage = [
        Coverage(sid, project, source, status, json.loads(error or "[]"))
        for sid, project, source, status, error in snapshots
    ]
    return report
