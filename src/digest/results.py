"""Stable result grouping, preserving all human review states."""

import json
import re
import sqlite3
from pathlib import PurePosixPath
from typing import Any

from digest.collectors.base import canonical, content_hash


def group_results(db: sqlite3.Connection) -> None:
    """Link completed tasks and their explicit references; keep unrelated work visible."""
    rows = db.execute(
        "SELECT id,project_id,source,kind,locator,observed_at,event_at,excerpt,meta,task_id "
        "FROM evidence ORDER BY observed_at,snapshot_id,rowid"
    ).fetchall()
    evidence = [
        {
            "id": r[0],
            "project": r[1],
            "source": r[2],
            "kind": r[3],
            "locator": r[4],
            "observed": r[5],
            "event": r[6],
            "excerpt": r[7],
            "meta": json.loads(r[8]),
            "task": r[9],
        }
        for r in rows
    ]
    tasks: dict[tuple[str, str], dict[str, Any]] = {}
    notes: dict[tuple[str, str], list[str]] = {}
    for item in evidence:
        if item["task"]:
            key = (item["project"], item["task"])
            tasks[key] = item
            notes.setdefault(key, []).append(item["excerpt"])
    completed = {
        key: item for key, item in tasks.items() if item["meta"].get("state") in {"review", "done"}
    }
    existing = {
        (r[0], r[1])
        for r in db.execute("SELECT project_id,task_id FROM result WHERE task_id IS NOT NULL")
    }
    eligible = set(completed) | existing
    commits: dict[tuple[str, str], set[str]] = {}
    for item in evidence:
        if item["kind"] == "commit":
            for project, task in eligible:
                if project == item["project"] and re.search(
                    r"(?<![\w-])" + re.escape(task) + r"(?![\w-])", item["excerpt"]
                ):
                    commits.setdefault((project, item["locator"]), set()).add(task)
    db.execute("BEGIN IMMEDIATE")
    try:
        for (project, task), item in completed.items():
            ident = f"res_{project}_{task}"
            db.execute(
                "INSERT INTO result(id,project_id,task_id,title,first_seen_at,completed_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
                "completed_at=COALESCE(result.completed_at,excluded.completed_at)",
                (
                    ident,
                    project,
                    task,
                    item["meta"].get("title", task),
                    item["observed"],
                    item["event"] or item["observed"],
                ),
            )
        for item in evidence:
            project = item["project"]
            links: set[str] = set()
            if item["task"] and (project, item["task"]) in eligible:
                links.add(item["task"])
            if item["kind"] == "commit":
                links |= commits.get((project, item["locator"]), set())
            if item["kind"] == "diff":
                links |= commits.get((project, item["locator"].split(":", 1)[0]), set())
            provenance = item["meta"].get("provenance", {})
            if provenance.get("kind") == "git":
                links |= commits.get((project, provenance.get("commit", "")), set())
            path = item["meta"].get("path")
            if isinstance(path, str):
                for key, texts in notes.items():
                    if (
                        key in eligible
                        and key[0] == project
                        and any(path in text for text in texts)
                    ):
                        links.add(key[1])
            for task in links:
                db.execute(
                    "INSERT OR IGNORE INTO result_evidence VALUES (?,?)",
                    (f"res_{project}_{task}", item["id"]),
                )
            if links or item["task"]:
                continue
            directory = (
                PurePosixPath(path).parts[0]
                if isinstance(path, str) and "/" in path
                else item["source"]
            )
            ident = f"res_{project}_" + content_hash(canonical(["outside", directory]))[:12]
            db.execute(
                "INSERT INTO result(id,project_id,title,first_seen_at) VALUES (?,?,?,?) "
                "ON CONFLICT(id) DO NOTHING",
                (ident, project, "Fuera del tablero · " + directory, item["observed"]),
            )
            db.execute("INSERT OR IGNORE INTO result_evidence VALUES (?,?)", (ident, item["id"]))
        db.commit()
    except BaseException:
        db.rollback()
        raise
