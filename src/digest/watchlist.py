"""Versioned human monitoring questions, independent of project task boards."""

import re
import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from digest.collectors.base import canonical, content_hash, utc
from digest.config import Config
from digest.notebook import append, metadata, revision
from digest.util.redact import known_secrets, redact_tree

IDENT = re.compile(r"wl_[a-f0-9]{32}")
STATES = {"active": "Activo", "paused": "Pausado", "archived": "Archivado"}


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    title: str = Field(min_length=1, max_length=160)
    question: str = Field(min_length=1, max_length=1000)
    projects: list[str] = Field(max_length=100)
    priority: int = Field(default=50, ge=0, le=100)
    state: Literal["active", "paused", "archived"] = "active"


def catalogue(db: sqlite3.Connection) -> list[dict[str, Any]]:
    result = []
    for name, encoded in db.execute(
        "SELECT key,value FROM meta WHERE key GLOB 'wl_item:*' ORDER BY key"
    ).fetchall():
        import json

        saved = revision(db, json.loads(encoded))
        if saved.get("kind") != "watchlist" or name != "wl_item:" + saved["item_id"]:
            raise ValueError("Watchlist identity changed")
        Item.model_validate(saved["values"])
        result.append(saved)
    return sorted(result, key=lambda s: (-s["values"]["priority"], s["item_id"]))


def expected(db: sqlite3.Connection) -> str:
    return content_hash(canonical([s["id"] for s in catalogue(db)]))


def draft(text: str, projects: list[str], priority: int) -> list[dict[str, Any]]:
    lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not 1 <= len(lines) <= 30:
        raise ValueError("Use between one and thirty questions")
    return [
        Item(title=line[:160], question=line, projects=projects, priority=priority).model_dump()
        for line in lines
    ]


def save(
    db: sqlite3.Connection,
    config: Config,
    values: list[dict[str, Any]],
    etag: str,
    nonce: str,
    *,
    item_id: str | None = None,
) -> list[str]:
    if not re.fullmatch(r"[a-f0-9]{32}", nonce) or not 1 <= len(values) <= 30:
        raise ValueError("Invalid watchlist submission")
    if item_id is not None and (not IDENT.fullmatch(item_id) or len(values) != 1):
        raise ValueError("Invalid watchlist identity")
    hidden = known_secrets(config)
    parsed = [Item.model_validate(v) for v in values]
    configured = {p.id for p in config.projects}
    for item in parsed:
        if (
            not item.title.strip()
            or not item.question.strip()
            or any(ord(c) < 32 and c not in "\n\r\t" for c in item.title + item.question)
            or len(set(item.projects)) != len(item.projects)
            or not set(item.projects) <= configured
        ):
            raise ValueError("Invalid watchlist values")
    cleaned = redact_tree([v.model_dump() for v in parsed], hidden)
    request = {"item_id": item_id, "values": cleaned, "expected": etag}
    previous_submission = metadata(db, "wl_submission:" + nonce)
    if previous_submission:
        if previous_submission["request"] != request:
            raise ValueError("Submission already used")
        return list(previous_submission["items"])
    current = catalogue(db)
    if etag != expected(db):
        raise ValueError("Watchlist changed; reload before saving")
    prior = next((s for s in current if s["item_id"] == item_id), None)
    if item_id is not None and prior is None:
        raise ValueError("Unknown watchlist item")
    active = sum(s["values"]["state"] == "active" for s in current if s["item_id"] != item_id)
    if active + sum(v["state"] == "active" for v in cleaned) > 30:
        raise ValueError("At most thirty active questions")
    scope = configured | {r[0] for r in db.execute("SELECT id FROM project")}
    if prior:
        scope.update(prior["privacy_projects"])
    ids = []
    db.execute("SAVEPOINT watchlist_save")
    try:
        for value in cleaned:
            ident = item_id or "wl_" + secrets.token_hex(16)
            append(
                db,
                {
                    "kind": "watchlist",
                    "item_id": ident,
                    "values": value,
                    "original": prior["original"] if prior else value,
                    "first_created_at": (
                        prior["first_created_at"] if prior else utc(datetime.now(UTC))
                    ),
                    "privacy_projects": sorted(scope),
                    "previous": prior["id"] if prior else None,
                },
                "wl_item:" + ident,
            )
            ids.append(ident)
        db.execute(
            "INSERT INTO meta(key,value) VALUES (?,?)",
            ("wl_submission:" + nonce, canonical({"request": request, "items": ids})),
        )
        db.execute("RELEASE watchlist_save")
    except BaseException:
        db.execute("ROLLBACK TO watchlist_save")
        db.execute("RELEASE watchlist_save")
        raise
    return ids


def history(db: sqlite3.Connection, item_id: str, page: int) -> tuple[list[dict[str, Any]], bool]:
    if not IDENT.fullmatch(item_id) or not 1 <= page <= 10000:
        raise ValueError("Invalid watchlist history")
    rows = db.execute(
        "SELECT json_extract(value,'$.id') FROM meta WHERE key GLOB 'nb_revision:*' "
        "AND json_extract(value,'$.kind')='watchlist' AND json_extract(value,'$.item_id')=? "
        "ORDER BY json_extract(value,'$.generation') DESC,key DESC LIMIT 21 OFFSET ?",
        (item_id, (page - 1) * 20),
    ).fetchall()
    return [revision(db, row[0]) for row in rows[:20]], len(rows) > 20


def freeze(db: sqlite3.Connection, config: Config) -> dict[str, Any]:
    configured = {p.id for p in config.projects}
    registered = {r[0] for r in db.execute("SELECT id FROM project")}
    remaining = 12000
    items = []
    for saved in catalogue(db):
        value = saved["values"]
        if value["state"] != "active":
            continue
        scope = set(saved["privacy_projects"]) | registered | configured
        entry = {
            "id": saved["item_id"],
            "revision": saved["id"],
            "values": value,
            "created_at": saved["first_created_at"] or saved["created_at"],
            "projects": value["projects"] or sorted(configured),
            "privacy_projects": sorted(scope),
            "omitted": None,
        }
        size = len(value["title"]) + len(value["question"])
        if not scope <= configured:
            entry["omitted"] = "privacy"
        elif size > remaining:
            entry["omitted"] = "budget"
        else:
            remaining -= size
        items.append(entry)
    payload = redact_tree({"version": 1, "items": items}, known_secrets(config))
    return {**payload, "hash": content_hash(canonical(payload))}
