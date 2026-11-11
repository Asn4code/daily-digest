"""Explicit human plan decisions with immutable history and optimistic concurrency."""

import json
import re
import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Any

from digest.collectors.base import canonical, content_hash, utc
from digest.config import Config
from digest.report.model import Report
from digest.review.records import document, enqueue
from digest.util.redact import known_secrets, redact


def meta(db: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def items(db: sqlite3.Connection, report: Report) -> list[dict[str, Any]]:
    plan = report.sections.get("plan", {})
    proposed = ([plan["mission"]] if plan.get("mission") else []) + plan.get("warmups", [])
    rows = db.execute(
        "SELECT id,kind,action,done_criterion,dependency,reason,origin,kanvas_task_id,"
        "accepted,edited_text FROM plan_item WHERE report_id=? ORDER BY id",
        (report.id,),
    ).fetchall()
    if len(rows) != len(proposed):
        raise ValueError("Plan catalogue differs from report")
    output = []
    keys = ("kind", "action", "done_criterion", "dependency", "reason", "origin", "kanvas_task_id")
    for row, proposal in zip(rows, proposed, strict=True):
        if row[1:8] != tuple(proposal[k] for k in keys):
            raise ValueError("Generated plan changed")
        human = meta(db, f"plan_human:{row[0]}", {})
        output.append(
            {
                "id": row[0],
                "report_id": report.id,
                "proposal": proposal,
                "kind": row[1],
                "action": row[9] if row[9] is not None else row[2],
                "done_criterion": human.get("done_criterion", row[3]),
                "dependency": human.get("dependency", row[4]),
                "accepted": bool(row[8]),
                "edited": row[9] is not None or bool(human.get("edited")),
                "decision": human.get("decision", "proposed"),
                "version": human.get("version", 0),
            }
        )
    return output


def active(db: sqlite3.Connection, config: Config) -> list[dict[str, Any]]:
    reports = [
        r[0]
        for r in db.execute(
            "SELECT DISTINCT report_id FROM plan_item WHERE accepted=1 ORDER BY report_id"
        )
    ]
    return [
        item for rid in reports for item in items(db, document(db, config, rid)) if item["accepted"]
    ]


def token(db: sqlite3.Connection, config: Config, report: Report) -> str:
    return content_hash(canonical({"items": items(db, report), "active": active(db, config)}))


def decide(
    db: sqlite3.Connection,
    config: Config,
    report_id: str,
    item_id: int,
    action: str,
    values: dict[str, str],
    expected: str,
    submission: str,
) -> str:
    if action not in {"save", "accept", "dismiss"} or not re.fullmatch(r"[a-f0-9]{32}", submission):
        raise ValueError("Invalid plan decision")
    if set(values) != {"action", "done_criterion", "dependency"}:
        raise ValueError("Invalid plan fields")
    if any(
        len(v) > 2000 or any(ord(c) < 32 and c not in "\r\n\t" for c in v) for v in values.values()
    ):
        raise ValueError("Invalid plan text")
    secrets_ = known_secrets(config)
    clean = {k: redact(v.strip(), secrets_) for k, v in values.items()}
    if not clean["action"] or not clean["done_criterion"]:
        raise ValueError("Action and completion criterion are required")
    request = {"report": report_id, "item": item_id, "action": action, "values": clean}
    prior = meta(db, "plan_submission:" + submission)
    if prior:
        if prior["request"] != request:
            raise ValueError("Submission already used")
        return str(prior["id"])
    report = document(db, config, report_id)
    candidates = items(db, report)
    chosen = next((i for i in candidates if i["id"] == item_id), None)
    if chosen is None or expected != token(db, config, report):
        raise ValueError("Plan changed; reload before deciding")
    previous = active(db, config)
    if action == "accept" and chosen["kind"] == "warmup" and not chosen["accepted"]:
        if sum(i["kind"] == "warmup" for i in previous) >= 2:
            raise ValueError("Choose at most two warmups")
    if action == "accept" and chosen["kind"] == "mission":
        db.execute("UPDATE plan_item SET accepted=0 WHERE kind='mission'")
    # Saving an already accepted item changes the active plan only by this
    # explicit human action. Prior snapshots retain the previous human text.
    accepted = action == "accept" or action == "save" and chosen["accepted"]
    edited = any((clean[k] or None) != (chosen["proposal"][k] or None) for k in clean)
    stamp = utc(datetime.now(UTC))
    adjustment = {
        "done_criterion": clean["done_criterion"],
        "dependency": clean["dependency"] or None,
        "edited": edited,
        "decision": action,
        "version": chosen["version"] + 1,
    }
    db.execute(
        "UPDATE plan_item SET accepted=?,edited_text=? WHERE id=?",
        (
            int(accepted),
            clean["action"] if clean["action"] != chosen["proposal"]["action"] else None,
            item_id,
        ),
    )
    db.execute(
        "INSERT INTO meta(key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (f"plan_human:{item_id}", canonical(adjustment)),
    )
    # A human override can mention any registered project; retain that scope
    # even when the edited words happen to equal a generated field later.
    if edited:
        known = {r[0] for r in db.execute("SELECT id FROM project")} | {
            p.id for p in config.projects
        }
        known.update(meta(db, f"plan_scope:{item_id}", []))
        db.execute(
            "INSERT INTO meta(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"plan_scope:{item_id}", canonical(sorted(known))),
        )
    ident = "plan_" + secrets.token_hex(16)
    updated = next(i for i in items(db, report) if i["id"] == item_id)
    snapshot = {
        "version": 1,
        "id": ident,
        "created_at": stamp,
        "report_id": report_id,
        "decision": action,
        "item": updated,
        "active": active(db, config),
    }
    db.execute(
        "INSERT INTO meta(key,value) VALUES (?,?)", ("plan_snapshot:" + ident, canonical(snapshot))
    )
    db.execute(
        "INSERT INTO meta(key,value) VALUES (?,?)",
        ("plan_snapshot_hash:" + ident, content_hash(canonical(snapshot))),
    )
    db.execute(
        "INSERT INTO meta(key,value) VALUES (?,?)",
        ("plan_submission:" + submission, canonical({"id": ident, "request": request})),
    )
    enqueue(db, "deliver", {"plan": ident}, "web")
    return ident


def snapshot(db: sqlite3.Connection, config: Config, ident: str) -> dict[str, Any]:
    if not re.fullmatch(r"plan_[a-f0-9]{32}", ident):
        raise ValueError("Invalid plan snapshot")
    value = meta(db, "plan_snapshot:" + ident)
    digest = db.execute(
        "SELECT value FROM meta WHERE key=?", ("plan_snapshot_hash:" + ident,)
    ).fetchone()
    if (
        not isinstance(value, dict)
        or value.get("id") != ident
        or not digest
        or content_hash(canonical(value)) != digest[0]
    ):
        raise ValueError("Plan snapshot changed")
    for entry in [value["item"], *value["active"]]:
        report = document(db, config, entry["report_id"])
        current = next((i for i in items(db, report) if i["id"] == entry["id"]), None)
        if current is None or entry["proposal"] != current["proposal"]:
            raise ValueError("Snapshot proposal changed")
    return value
