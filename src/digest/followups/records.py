"""Immutable requests, bounded inputs and certified revisions in existing metadata."""

import json
import re
import secrets
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from digest import queue
from digest.collectors.base import canonical, content_hash, utc
from digest.config import Config
from digest.followups.selection import resolve
from digest.report.loading import MAX_REPORT_BYTES, load_ready
from digest.report.model import Report
from digest.util.fs import read_bounded
from digest.util.redact import known_secrets, redact, redact_tree

IDENTIFIER = re.compile(r"fu_[a-f0-9]{32}")


def meta(db: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def state(db: sqlite3.Connection, key: str, value: Any) -> None:
    db.execute(
        "INSERT INTO meta(key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, canonical(value)),
    )


def immutable(db: sqlite3.Connection, key: str, value: dict[str, Any]) -> None:
    db.execute("SAVEPOINT followup_immutable")
    try:
        db.execute("INSERT INTO meta(key,value) VALUES (?,?)", (key, canonical(value)))
        db.execute(
            "INSERT INTO meta(key,value) VALUES (?,?)",
            (key + ":hash", canonical(content_hash(canonical(value)))),
        )
        db.execute("RELEASE SAVEPOINT followup_immutable")
    except BaseException:
        db.execute("ROLLBACK TO SAVEPOINT followup_immutable")
        db.execute("RELEASE SAVEPOINT followup_immutable")
        raise


def verified(db: sqlite3.Connection, key: str) -> dict[str, Any]:
    value = meta(db, key)
    if not isinstance(value, dict) or content_hash(canonical(value)) != meta(db, key + ":hash"):
        raise ValueError("Follow-up record changed")
    return value


def source(db: sqlite3.Connection, config: Config, ident: str) -> tuple[Report, str, int]:
    report, path, _ = load_ready(db, config, ident)
    root = Path(config.paths.data_dir).resolve() / "reports"
    raw = read_bounded(root, path.resolve().relative_to(root), max_bytes=MAX_REPORT_BYTES)
    revision = db.execute("SELECT revision FROM report WHERE id=?", (ident,)).fetchone()[0]
    return report, content_hash(raw), revision


def privacy(db: sqlite3.Connection, config: Config, report: Report) -> set[str]:
    ids = {p.id for p in config.projects} | {r[0] for r in db.execute("SELECT id FROM project")}
    ids.update(e.project for e in report.evidence)
    for package in report.packages.values():
        ids.update(package.get("project_ids", []))

    def ancestors(value: Any) -> None:
        if isinstance(value, dict):
            ids.update(value.get("privacy_projects", []))
            for item in value.values():
                if isinstance(item, (dict, list)):
                    ancestors(item)
        elif isinstance(value, list):
            for item in value:
                ancestors(item)

    ancestors(report.human_context)
    return ids


def submit(
    db: sqlite3.Connection,
    config: Config,
    report_id: str,
    identifiers: list[str],
    question: str,
    intent: str,
    expected: str,
    nonce: str,
) -> str:
    if intent not in {"explain", "check"} or not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise ValueError("Invalid follow-up request")
    if not 1 <= len(question.strip()) <= 2000 or any(
        ord(c) < 32 and c not in "\n\r\t" for c in question
    ):
        raise ValueError("Invalid question")
    question = redact(question.strip(), known_secrets(config))
    report, hashed, revision = source(db, config, report_id)
    if hashed != expected or report.kind != "daily":
        raise ValueError("Original report changed or unsupported")
    resolve(report, identifiers)
    request = {
        "source_id": report_id,
        "source_hash": hashed,
        "source_revision": revision,
        "selections": identifiers,
        "question": question,
        "intent": intent,
    }
    prior = meta(db, "followup_submission:" + nonce)
    if prior:
        if prior["request"] != request:
            raise ValueError("Submission already used")
        return str(prior["id"])
    ident = "fu_" + secrets.token_hex(16)
    value = {
        "version": 1,
        "id": ident,
        "created_at": utc(datetime.now(UTC)),
        **request,
        "privacy_projects": sorted(privacy(db, config, report)),
    }
    job = queue.insert(db, "contrast", {"followup": ident}, "web")
    value["job"] = job
    immutable(db, "followup_request:" + ident, value)
    state(db, "followup_submission:" + nonce, {"request": request, "id": ident})
    state(db, "followup_state:" + ident, {"state": "queued", "attempts": 0, "job": job})
    return ident


def request(db: sqlite3.Connection, config: Config, ident: str) -> tuple[dict[str, Any], Report]:
    if not IDENTIFIER.fullmatch(ident):
        raise ValueError("Unknown follow-up")
    value = verified(db, "followup_request:" + ident)
    if value.get("id") != ident or value.get("version") != 1:
        raise ValueError("Invalid follow-up identity")
    report, hashed, revision = source(db, config, value["source_id"])
    if (hashed, revision) != (value["source_hash"], value["source_revision"]):
        raise ValueError("Follow-up source changed")
    resolve(report, value["selections"])
    return value, report


def input_package(
    db: sqlite3.Connection, config: Config, ident: str, *, now: datetime
) -> dict[str, Any]:
    from digest.followups.checks import metric_summary

    value, report = request(db, config, ident)
    existing = meta(db, "followup_input:" + ident)
    if existing is not None:
        package = verified(db, "followup_input:" + ident)
        if package["request_hash"] != content_hash(canonical(value)):
            raise ValueError("Follow-up input binding changed")
        return package
    selected, entries = resolve(report, value["selections"])
    if len(entries) > 32 or len(canonical([asdict(e) for e in entries])) > 64000:
        raise ValueError("Follow-up source budget exceeded")
    receipts = []
    extra = []
    if value["intent"] == "check":
        for entry in entries:
            receipt = metric_summary(config, entry, now=now)
            if entry.kind != "metric":
                receipt["method"] = "capability_scope_v1"
                receipt["limits"] = [
                    "Releer una declaración no verifica el experimento; "
                    "no hay un comprobador ejecutable para esta fuente."
                ]
            rid = "ev_" + content_hash(canonical([ident, receipt]))[:12]
            receipt["evidence_id"] = rid
            receipts.append(receipt)
            extra.append(
                {
                    "id": rid,
                    "project": entry.project,
                    "kind": "followup_check",
                    "locator": ident + "/" + entry.id,
                    "excerpt": canonical(receipt),
                    "observed_at": utc(now),
                    "event_at": None,
                    "time_quality": "observed",
                    "meta": receipt,
                    "content_hash": content_hash(canonical(receipt)),
                    "context_only": True,
                }
            )
            if (
                receipt["current_hash"]
                and receipt["current_hash"] != entry.content_hash
                and receipt["computed"]
            ):
                mid = (
                    "ev_"
                    + content_hash(canonical([ident, entry.id, receipt["current_hash"], "data"]))[
                        :12
                    ]
                )
                extra.append(
                    {
                        "id": mid,
                        "project": entry.project,
                        "kind": "metric",
                        "locator": ident + "/data/" + entry.id,
                        "excerpt": canonical(receipt["computed"]),
                        "observed_at": utc(now),
                        "event_at": None,
                        "time_quality": "observed",
                        "meta": {
                            "path": entry.meta.get("path"),
                            "stats": receipt["computed"],
                            "source_evidence": entry.id,
                            "origin": "followup_data",
                        },
                        "content_hash": receipt["current_hash"],
                        "context_only": True,
                    }
                )
    package = redact_tree(
        {
            "request_hash": content_hash(canonical(value)),
            "project_ids": value["privacy_projects"],
            "result_ids": [],
            "context": {
                "source_id": report.id,
                "source_revision": value["source_revision"],
                "selections": [asdict(s) for s in selected],
                "question": value["question"],
                "intent": value["intent"],
                "checks": receipts,
            },
            "evidence": [asdict(e) for e in entries] + extra,
        },
        known_secrets(config),
    )
    if len(canonical(package)) > min(128000, config.limits.max_project_package_chars):
        raise ValueError("Follow-up input budget exceeded")
    db.execute("BEGIN IMMEDIATE")
    try:
        for entry in package["evidence"]:
            if entry["id"] not in {e.id for e in entries}:
                db.execute(
                    "INSERT INTO evidence(id,project_id,source,kind,locator,observed_at,"
                    "time_quality,content_hash,excerpt,meta) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        entry["id"],
                        entry["project"],
                        "followup",
                        entry["kind"],
                        entry["locator"],
                        entry["observed_at"],
                        "observed",
                        entry["content_hash"],
                        entry["excerpt"],
                        canonical(entry["meta"]),
                    ),
                )
        immutable(db, "followup_input:" + ident, package)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    assert isinstance(package, dict)
    return package


def retry(
    db: sqlite3.Connection,
    config: Config,
    ident: str,
    nonce: str,
    *,
    revision: int | None = None,
    channel: str | None = None,
) -> int:
    value, _ = request(db, config, ident)
    intent = {"followup": ident, "revision": revision, "channel": channel}
    prior = queue.submission(db, nonce, intent)
    if prior is not None:
        return prior
    if revision is not None:
        from digest.followups.generate import read_revision

        read_revision(db, config, ident, revision)
        if channel not in {"email", "obsidian", "drive"}:
            raise ValueError("Unknown channel")
        delivery = meta(
            db, f"followup_delivery:{ident}:r{revision}:{channel}", {"state": "pending"}
        )
        if delivery["state"] not in {"pending", "failed"}:
            raise ValueError("Delivery cannot be retried")
        row = db.execute(
            "SELECT id FROM job WHERE kind='deliver' AND state IN ('queued','running') "
            "AND json_extract(params,'$.followup')=? AND json_extract(params,'$.revision')=? "
            "AND json_extract(params,'$.channel')=?",
            (ident, revision, channel),
        ).fetchone()
        job = row[0] if row else queue.insert(db, "deliver", intent, "web")
    else:
        job = value["job"]
        current = db.execute(
            "SELECT state FROM job WHERE id=? AND kind='contrast'", (job,)
        ).fetchone()
        if not current or meta(db, "followup_ready:" + ident) is not None:
            raise ValueError("Follow-up is not pending")
        if current[0] == "failed":
            db.execute(
                "UPDATE job SET state='queued',error=NULL,finished_at=NULL WHERE id=?", (job,)
            )
            saved = meta(db, "followup_state:" + ident)
            state(db, "followup_state:" + ident, {**saved, "state": "queued"})
        elif current[0] not in {"queued", "running"}:
            raise ValueError("Job cannot be resumed")
    return queue.remember(db, nonce, intent, int(job))
