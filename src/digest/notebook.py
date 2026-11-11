"""Personal annotations over verified, read-only Kanvas snapshots."""

import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from digest.collectors.base import canonical, content_hash, utc
from digest.config import Config, ProjectConfig
from digest.util.fs import read_bounded
from digest.util.redact import known_secrets, redact, redact_tree

IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")
STATES = {"proposed", "todo", "doing", "review", "done"}


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    base: int = Field(default=50, ge=0, le=100)
    daily_step: int = Field(default=1, ge=0, le=10)
    cap: int = Field(default=20, ge=0, le=100)
    enabled: bool = True


class Personal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    base: int | None = Field(default=None, ge=0, le=100)
    aging: Literal["inherit", "on", "off"] = "inherit"
    note: str = Field(default="", max_length=4000)


def timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.astimezone(UTC) if stamp.tzinfo else None
    except ValueError:
        return None


def key(project_id: str, task_id: str) -> str:
    if not IDENTIFIER.fullmatch(project_id) or not IDENTIFIER.fullmatch(task_id):
        raise ValueError("Unknown notebook task")
    return content_hash(canonical([project_id, task_id]))


def metadata(db: sqlite3.Connection, name: str, default: Any = None) -> Any:
    row = db.execute("SELECT value FROM meta WHERE key=?", (name,)).fetchone()
    return json.loads(row[0]) if row else default


def revision(db: sqlite3.Connection, ident: str) -> dict[str, Any]:
    if not re.fullmatch(r"nb_[a-f0-9]{32}", ident):
        raise ValueError("Unknown notebook revision")
    value = metadata(db, "nb_revision:" + ident)
    digest = metadata(db, "nb_hash:" + ident)
    if (
        not isinstance(value, dict)
        or value.get("id") != ident
        or content_hash(canonical(value)) != digest
    ):
        raise ValueError("Notebook revision changed")
    return value


def settings(db: sqlite3.Connection) -> tuple[Settings, str | None]:
    ident = metadata(db, "nb_settings")
    return (
        (Settings.model_validate(revision(db, ident)["values"]), ident)
        if ident
        else (Settings(), None)
    )


@dataclass
class Source:
    project: str
    name: str
    objective: str
    snapshot_id: int | None
    observed_at: str | None
    stale: bool
    tasks: dict[str, dict[str, Any]]
    first_seen: dict[str, str]


def source(db: sqlite3.Connection, config: Config, project: ProjectConfig) -> Source:
    hidden = known_secrets(config)
    name, objective = redact(project.name, hidden), redact(project.objective, hidden)
    latest = db.execute(
        "SELECT id,status FROM snapshot WHERE project_id=? AND source='kanvas' "
        "ORDER BY id DESC LIMIT 1",
        (project.id,),
    ).fetchone()
    row = db.execute(
        "SELECT id,taken_at,payload_path,content_hash,status FROM snapshot WHERE project_id=? "
        "AND source='kanvas' AND status IN ('ok','partial') AND payload_path IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (project.id,),
    ).fetchone()
    empty = Source(project.id, name, objective, None, None, True, {}, {})
    if not row:
        return empty
    try:
        root = Path(config.paths.data_dir).resolve()
        path = Path(row[2]).resolve()
        relative = path.relative_to(root / "snapshots" / project.id)
        if any(path.is_relative_to(Path(p.root).resolve()) for p in config.projects):
            raise ValueError("Snapshot overlaps a project")
        raw = read_bounded(root / "snapshots" / project.id, relative, max_bytes=12_000_000)
        if content_hash(raw) != row[3]:
            raise ValueError("Snapshot changed")
        value = json.loads(raw)
        tasks = value["tasks"]
        if not isinstance(tasks, dict):
            raise ValueError("Invalid task catalogue")
        for ident, task in tasks.items():
            if (
                not IDENTIFIER.fullmatch(ident)
                or not isinstance(task, dict)
                or task.get("id") != ident
                or task.get("state") not in STATES
                or not isinstance(task.get("title"), str)
                or not isinstance(task.get("desc", ""), str)
                or not isinstance(task.get("deps", []), list)
                or not isinstance(task.get("notes", []), list)
                or any(
                    not isinstance(n, dict) or not isinstance(n.get("text"), str)
                    for n in task.get("notes", [])
                )
                or any(
                    not isinstance(dep, str) or not IDENTIFIER.fullmatch(dep)
                    for dep in task.get("deps", [])
                )
            ):
                raise ValueError("Invalid task catalogue")
        tasks = {ident: {**task, "deps": task.get("deps", [])} for ident, task in tasks.items()}
        first_seen = dict(
            db.execute(
                "SELECT task_id,min(observed_at) FROM evidence WHERE project_id=? "
                "AND source='kanvas' "
                "AND kind='task_transition' GROUP BY task_id",
                (project.id,),
            )
        )
        return Source(
            project.id,
            name,
            objective,
            row[0],
            row[1],
            latest is None or latest[0] != row[0] or row[4] != "ok",
            tasks,
            first_seen,
        )
    except (OSError, ValueError, KeyError, TypeError):
        return empty


def identity(task: dict[str, Any], first_seen: str | None) -> str:
    created = timestamp(task.get("at"))
    return utc(created) if created else "observed:" + (first_seen or "unknown")


def personal(
    db: sqlite3.Connection, project_id: str, task_id: str, birth: str
) -> tuple[Personal, str | None, bool]:
    ident = metadata(db, "nb_task:" + key(project_id, task_id))
    if not ident:
        return Personal(), None, False
    value = revision(db, ident)
    if value["project_id"] != project_id or value["task_id"] != task_id:
        raise ValueError("Notebook identity changed")
    if value["source_identity"] != birth:
        return Personal(), ident, True
    return Personal.model_validate(value["values"]), ident, False


def task_view(
    db: sqlite3.Connection,
    config: Config,
    board: Source,
    task_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    task = board.tasks.get(task_id)
    if task is None:
        raise ValueError("Unknown notebook task")
    observed = board.first_seen.get(task_id) or board.observed_at
    birth = identity(task, observed)
    user, rev, changed = personal(db, board.project, task_id, birth)
    rule, setting_id = settings(db)
    created = timestamp(task.get("at"))
    origin = created or timestamp(observed)
    instant = now or datetime.now(UTC)
    days = max(0, int((instant - origin).total_seconds() // 86400)) if origin else 0
    enabled = rule.enabled if user.aging == "inherit" else user.aging == "on"
    base = rule.base if user.base is None else user.base
    bonus = min(rule.cap, days * rule.daily_step) if enabled and task["state"] != "done" else 0
    priority = min(100, base + bonus)
    blockers = [
        dep for dep in task["deps"] if dep not in board.tasks or board.tasks[dep]["state"] != "done"
    ]
    expected = content_hash(canonical([board.snapshot_id, rev, setting_id, birth]))
    return {
        "id": task_id,
        "project_id": board.project,
        "project_name": board.name,
        "title": task["title"],
        "description": task.get("desc", ""),
        "state": task["state"],
        "deps": task["deps"],
        "blockers": blockers,
        "stale": board.stale,
        "available": task["state"] in {"todo", "doing"} and not blockers and not board.stale,
        "created_at": utc(created) if created else None,
        "first_seen": observed,
        "date_basis": "event" if created else "observed",
        "future_date": bool(origin and origin > instant),
        "age_days": days,
        "base": base,
        "aging_bonus": priority - base,
        "suggested": priority,
        "personal": user.model_dump(),
        "revision": rev,
        "identity_changed": changed,
        "source_identity": birth,
        "snapshot_id": board.snapshot_id,
        "expected": expected,
        "objective": board.objective,
        "source_notes": [
            {
                "text": n["text"][:4000],
                "truncated": len(n["text"]) > 4000,
                "by": n.get("by"),
                "at": utc(stamp) if (stamp := timestamp(n.get("edited") or n.get("at"))) else None,
            }
            for n in task.get("notes", [])[-20:]
        ],
        "source_note_count": len(task.get("notes", [])),
    }


def catalogue(
    db: sqlite3.Connection, config: Config, *, now: datetime | None = None
) -> tuple[list[dict[str, Any]], list[Source]]:
    boards = [source(db, config, project) for project in config.projects]
    tasks = [
        task_view(db, config, board, ident, now=now) for board in boards for ident in board.tasks
    ]
    visible = {(t["project_id"], t["id"]) for t in tasks}
    configured = {p.id for p in config.projects}
    for (encoded,) in db.execute("SELECT value FROM meta WHERE key GLOB 'nb_task:*'").fetchall():
        saved = revision(db, json.loads(encoded))
        pair = (saved["project_id"], saved["task_id"])
        if pair[0] in configured and pair not in visible:
            tasks.append(task(db, config, *pair, now=now))
    tasks.sort(key=lambda t: (not t["available"], -t["suggested"], t["project_id"], t["id"]))
    return tasks, boards


def task(
    db: sqlite3.Connection,
    config: Config,
    project_id: str,
    task_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    project = next((p for p in config.projects if p.id == project_id), None)
    if project is None:
        raise ValueError("Unknown notebook project")
    board = source(db, config, project)
    if task_id in board.tasks:
        return task_view(db, config, board, task_id, now=now)
    ident = metadata(db, "nb_task:" + key(project_id, task_id))
    if not ident:
        raise ValueError("Unknown notebook task")
    saved = revision(db, ident)
    if saved["project_id"] != project_id or saved["task_id"] != task_id:
        raise ValueError("Notebook identity changed")
    original = saved.get("source", {})
    historical = {
        "id": task_id,
        "title": original.get("title", task_id),
        "desc": original.get("description", ""),
        "at": original.get("created_at"),
        "state": original.get("state", "todo"),
        "deps": [],
        "notes": [],
    }
    archived = Source(
        board.project,
        board.name,
        board.objective,
        board.snapshot_id,
        original.get("first_seen"),
        True,
        {task_id: historical},
        {task_id: original.get("first_seen")},
    )
    result = task_view(db, config, archived, task_id, now=now)
    result.update(
        archived=True,
        last_state=historical["state"],
        state="archived",
        available=False,
        aging_bonus=0,
        suggested=result["base"],
    )
    return result


def append(db: sqlite3.Connection, value: dict[str, Any], pointer: str) -> str:
    ident = "nb_" + secrets.token_hex(16)
    prior = revision(db, value["previous"]) if value.get("previous") else None
    value = {
        **value,
        "version": 1,
        "generation": prior["generation"] + 1 if prior else 1,
        "id": ident,
        "created_at": utc(datetime.now(UTC)),
    }
    for name, payload in (
        ("nb_revision:" + ident, value),
        ("nb_hash:" + ident, content_hash(canonical(value))),
    ):
        db.execute("INSERT INTO meta(key,value) VALUES (?,?)", (name, canonical(payload)))
    db.execute(
        "INSERT INTO meta(key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (pointer, canonical(ident)),
    )
    return ident


def save(
    db: sqlite3.Connection,
    config: Config,
    project_id: str,
    task_id: str,
    values: dict[str, Any],
    expected: str,
    nonce: str,
) -> str:

    user = Personal.model_validate(values)
    if any(ord(c) < 32 and c not in "\r\n\t" for c in user.note):
        raise ValueError("Invalid note")
    user.note = redact(user.note, known_secrets(config))
    request = {"notebook": [project_id, task_id], "values": user.model_dump()}
    # A notebook edit stores a revision identifier; it never creates a technical job.
    if not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise ValueError("Invalid submission")
    prior = metadata(db, "nb_submission:" + nonce)
    if prior:
        if prior["request"] != request:
            raise ValueError("Submission already used")
        return str(prior["revision"])
    current = task(db, config, project_id, task_id)
    if expected != current["expected"]:
        raise ValueError("Notebook changed; reload before saving")
    previous = revision(db, current["revision"]) if current["revision"] else None
    privacy = {p.id for p in config.projects} | {r[0] for r in db.execute("SELECT id FROM project")}
    if previous:
        privacy.update(previous["privacy_projects"])
    ident = append(
        db,
        {
            "kind": "task",
            "project_id": project_id,
            "task_id": task_id,
            "source_identity": current["source_identity"],
            "values": user.model_dump(),
            "privacy_projects": sorted(privacy),
            "previous": current["revision"],
            "source": {
                "title": current["title"],
                "description": current["description"],
                "created_at": current["created_at"],
                "first_seen": current["first_seen"],
                "state": current.get("last_state", current["state"]),
                "snapshot_id": current["snapshot_id"],
            },
        },
        "nb_task:" + key(project_id, task_id),
    )
    db.execute(
        "INSERT INTO meta(key,value) VALUES (?,?)",
        ("nb_submission:" + nonce, canonical({"request": request, "revision": ident})),
    )
    return ident


def save_settings(
    db: sqlite3.Connection, values: dict[str, Any], expected: str | None, nonce: str
) -> str:
    rule = Settings.model_validate(values)
    request = {"notebook_settings": rule.model_dump()}
    if not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise ValueError("Invalid submission")
    prior = metadata(db, "nb_submission:" + nonce)
    if prior:
        if prior["request"] != request:
            raise ValueError("Submission already used")
        return str(prior["revision"])
    _, current = settings(db)
    if current != expected:
        raise ValueError("Settings changed; reload before saving")
    ident = append(
        db, {"kind": "settings", "values": rule.model_dump(), "previous": current}, "nb_settings"
    )
    db.execute(
        "INSERT INTO meta(key,value) VALUES (?,?)",
        ("nb_submission:" + nonce, canonical({"request": request, "revision": ident})),
    )
    return ident


def history(
    db: sqlite3.Connection, project_id: str, task_id: str, page: int = 1
) -> tuple[list[dict[str, Any]], bool]:
    if not 1 <= page <= 10000:
        raise ValueError("Invalid history page")
    key(project_id, task_id)
    rows = db.execute(
        "SELECT json_extract(value,'$.id') FROM meta WHERE key GLOB 'nb_revision:*' "
        "AND json_extract(value,'$.kind')='task' AND json_extract(value,'$.project_id')=? "
        "AND json_extract(value,'$.task_id')=? "
        "ORDER BY json_extract(value,'$.generation') DESC,key DESC LIMIT 21 OFFSET ?",
        (project_id, task_id, (page - 1) * 20),
    ).fetchall()
    return [revision(db, r[0]) for r in rows[:20]], len(rows) > 20


def preferences(
    db: sqlite3.Connection, config: Config, candidates: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], set[str], bool]:
    result = []
    rule, setting_id = settings(db)
    if setting_id and candidates:
        result.append(
            {
                "origin": "human_notebook_settings",
                "revision": setting_id,
                "rules": rule.model_dump(),
            }
        )
    scope: set[str] = set()
    remaining = 6000
    omitted = False
    for item in candidates:
        personal_data = item.get("notebook", {})
        ident = personal_data.get("revision")
        if not ident:
            continue
        saved = revision(db, ident)
        scope.update(saved["privacy_projects"])
        data = {
            "project_id": item["project_id"],
            "task_id": item["id"],
            "origin": "human_notebook",
            "base": personal_data["base"],
            "aging_bonus": personal_data["aging_bonus"],
            "suggested": personal_data["suggested"],
            "revision": ident,
        }
        note = saved["values"]["note"]
        if len(note) <= remaining:
            data["note"] = note
            remaining -= len(note)
        else:
            data["note_omitted"] = "package_budget"
            omitted = True
        result.append(data)
    return redact_tree(result, known_secrets(config)), scope, omitted
