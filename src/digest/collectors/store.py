"""Persist immutable captures and idempotent evidence in the published schema."""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from digest.collectors.base import CaptureContext, CollectorOutput, canonical, content_hash, utc
from digest.config import ProjectConfig


def previous_payload(db: sqlite3.Connection, project_id: str, source: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT payload_path FROM snapshot WHERE project_id=? AND source=? "
        "AND status IN ('ok','partial') AND payload_path IS NOT NULL ORDER BY id DESC LIMIT 1",
        (project_id, source),
    ).fetchone()
    if not row:
        return None
    parsed: dict[str, Any] = json.loads(Path(row[0]).read_text())
    return parsed


def persist(
    db: sqlite3.Connection,
    project: ProjectConfig,
    source: str,
    output: CollectorOutput,
    ctx: CaptureContext,
) -> list[str]:
    """Keep failures as coverage, but retain the last usable comparison payload."""
    root = Path(project.root).resolve()
    data = ctx.data_dir.resolve()
    if data.is_relative_to(root):
        raise ValueError("Output directory must be outside the observed project")
    payload = canonical(output.snapshot_payload) if output.snapshot_payload is not None else None
    path: Path | None = None
    if payload is not None:
        directory = data / "snapshots" / project.id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (uuid4().hex + ".json")
        with path.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "INSERT INTO project(id,name,root,objective,priority,external_allowed,config_hash) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
            "root=excluded.root,objective=excluded.objective,priority=excluded.priority, "
            "external_allowed=excluded.external_allowed,config_hash=excluded.config_hash",
            (
                project.id,
                project.name,
                project.root,
                project.objective,
                project.priority,
                int(project.external_allowed),
                content_hash(canonical(project.model_dump())),
            ),
        )
        cursor = db.execute(
            "INSERT INTO snapshot(project_id,source,taken_at,schema_version,content_hash,"
            "payload_path,status,error) VALUES (?,?,?,?,?,?,?,?)",
            (
                project.id,
                source,
                utc(ctx.observed_at),
                "1",
                content_hash(payload) if payload else None,
                str(path) if path else None,
                output.status,
                canonical([asdict(item) for item in output.omitted]),
            ),
        )
        ids = []
        for draft in output.evidence:
            hashed = content_hash(draft.content)
            ident = (
                "ev_" + content_hash(canonical([project.id, source, draft.locator, hashed]))[:12]
            )
            db.execute(
                "INSERT INTO evidence(id,project_id,source,kind,locator,observed_at,event_at,"
                "time_quality,content_hash,excerpt,meta,task_id,snapshot_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (
                    ident,
                    project.id,
                    source,
                    draft.kind,
                    draft.locator,
                    utc(draft.observed_at),
                    utc(draft.event_at) if draft.event_at else None,
                    "event" if draft.event_at else "observed",
                    hashed,
                    draft.excerpt[: ctx.limits.max_excerpt_chars],
                    canonical(draft.meta),
                    draft.task_id,
                    cursor.lastrowid,
                ),
            )
            ids.append(ident)
        db.commit()
        return ids
    except BaseException:
        db.rollback()
        raise
