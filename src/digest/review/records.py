"""Transactional review records; submitted human text is immutable."""

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from digest.capture import validate_data_directory
from digest.collectors.base import canonical, content_hash, utc
from digest.config import Config
from digest.llm.schemas import Contrast
from digest.llm.validator import EvidencePackage, validate
from digest.report.loading import load_ready
from digest.report.model import Report, ResultEntry
from digest.util.fs import safe_path
from digest.util.redact import known_secrets, redact

FIELDS = {
    "full": {
        "purpose": "Propósito",
        "observation": "Observación",
        "limits": "Límites",
        "consequence": "Consecuencia",
    },
    "short": {"shows": "Qué muestra", "importance": "Por qué importa", "unknown": "Qué no sé"},
    "minimal": {"doubt": "Mi duda"},
}


@contextmanager
def writing(config: Config) -> Iterator[sqlite3.Connection]:
    root = validate_data_directory(config)
    path = safe_path(root, "digest.db", max_bytes=4_000_000_000)
    db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5, isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def document(db: sqlite3.Connection, config: Config, report_id: str) -> Report:
    report, path, _ = load_ready(db, config, report_id)
    path.relative_to(Path(config.paths.data_dir).resolve() / "reports")
    return report


def item(report: Report, result_id: str) -> ResultEntry:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", result_id):
        raise ValueError("Invalid result ID")
    found = next((r for r in report.results if r.id == result_id), None)
    if found is None:
        raise ValueError("Unknown result")
    return found


def scope(report: Report, result_id: str) -> EvidencePackage:
    result = item(report, result_id)
    return EvidencePackage(
        {e.id: e for e in report.evidence if e.id in result.evidence},
        {result.project},
        {result.id},
    )


def open_review(db: sqlite3.Connection, result_id: str) -> str | None:
    row = db.execute(
        "SELECT id FROM review WHERE result_id=? AND decision IS NULL "
        "ORDER BY submitted_at,id LIMIT 1",
        (result_id,),
    ).fetchone()
    return str(row[0]) if row else None


def text_fields(config: Config, mode: str, values: dict[str, str]) -> dict[str, str]:
    if mode not in FIELDS or set(values) != set(FIELDS[mode]):
        raise ValueError("Invalid review fields")
    if any(
        len(v) > 2000 or any(ord(c) < 32 and c not in "\n\t\r" for c in v) for v in values.values()
    ):
        raise ValueError("Invalid human text")
    if mode != "minimal" and not all(v.strip() for v in values.values()):
        raise ValueError("Missing review fields")
    secrets = known_secrets(config)
    return {k: redact(v.strip(), secrets) for k, v in values.items()}


def submit(
    db: sqlite3.Connection,
    config: Config,
    report_id: str,
    result_id: str,
    mode: str,
    values: dict[str, str],
    *,
    requested_by: str = "web",
    postpone: bool = False,
    submission_id: str | None = None,
) -> str:
    report = document(db, config, report_id)
    item(report, result_id)
    clean = text_fields(config, mode, values)
    if submission_id is not None:
        if not re.fullmatch(r"[a-f0-9]{32}", submission_id):
            raise ValueError("Invalid submission ID")
        prior = db.execute(
            "SELECT value FROM meta WHERE key=?", ("review_submission:" + submission_id,)
        ).fetchone()
        if prior:
            stored, _ = read(db, config, prior[0])
            if (stored["report_id"], stored["result_id"], stored["mode"], stored["human_text"]) == (
                report_id,
                result_id,
                mode,
                clean,
            ):
                return str(prior[0])
            raise ValueError("Submission has already been used")
    if mode == "minimal" and not postpone and not clean["doubt"]:
        raise ValueError("A doubt or postponement is required")
    existing = open_review(db, result_id)
    if existing:
        row = db.execute("SELECT mode,human_text FROM review WHERE id=?", (existing,)).fetchone()
        if row == (mode, canonical(clean)):
            if submission_id is not None:
                db.execute(
                    "INSERT INTO meta(key,value) VALUES (?,?)",
                    ("review_submission:" + submission_id, existing),
                )
            return existing
        raise ValueError("A review is already open")
    count = db.execute("SELECT count(*) FROM review WHERE result_id=?", (result_id,)).fetchone()[0]
    ident = f"rev_{result_id}_{count + 1}"
    stamp = utc(datetime.now(UTC))
    minimal_decision = (
        ("postponed" if postpone else "needs_clarification") if mode == "minimal" else None
    )
    doubts = [clean["doubt"]] if mode == "minimal" and clean["doubt"] else []
    db.execute(
        "INSERT INTO review(id,result_id,proposed_in_report,mode,human_text,submitted_at,"
        "decision,decided_at,doubts) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            ident,
            result_id,
            report_id,
            mode,
            canonical(clean),
            stamp,
            minimal_decision,
            stamp if minimal_decision else None,
            canonical(doubts),
        ),
    )
    db.execute(
        "UPDATE result SET review_state=? WHERE id=?", (minimal_decision or "submitted", result_id)
    )
    enqueue(db, "deliver" if mode == "minimal" else "contrast", {"review": ident}, requested_by)
    if submission_id is not None:
        db.execute(
            "INSERT INTO meta(key,value) VALUES (?,?)",
            ("review_submission:" + submission_id, ident),
        )
    return ident


def enqueue(db: sqlite3.Connection, kind: str, params: dict[str, Any], requested_by: str) -> None:
    db.execute(
        "INSERT INTO job(kind,params,requested_by,state,created_at) VALUES (?,?,?,'queued',?)",
        (kind, canonical(params), requested_by, utc(datetime.now(UTC))),
    )


def read(db: sqlite3.Connection, config: Config, review_id: str) -> tuple[dict[str, Any], Report]:
    row = db.execute(
        "SELECT id,result_id,proposed_in_report,mode,human_text,submitted_at,contrast,"
        "decision,decided_at,doubts FROM review WHERE id=?",
        (review_id,),
    ).fetchone()
    if not row:
        raise ValueError("Unknown review")
    record = dict(
        zip(
            (
                "id",
                "result_id",
                "report_id",
                "mode",
                "human_text",
                "submitted_at",
                "contrast",
                "decision",
                "decided_at",
                "doubts",
            ),
            row,
            strict=True,
        )
    )
    report = document(db, config, record["report_id"])
    item(report, record["result_id"])
    record["human_text"] = json.loads(record["human_text"])
    record["doubts"] = json.loads(record["doubts"])
    human = record["human_text"]
    if (
        record["mode"] not in FIELDS
        or not isinstance(human, dict)
        or set(human) != set(FIELDS[record["mode"]])
        or any(not isinstance(v, str) or len(v) > 2000 for v in human.values())
        or not isinstance(record["doubts"], list)
        or any(not isinstance(d, str) or len(d) > 2000 for d in record["doubts"])
    ):
        raise ValueError("Invalid human review record")
    record["model_info"] = {}
    if record["contrast"]:
        parsed = Contrast.model_validate_json(record["contrast"])
        check_contrast(parsed, report, record)
        certificate = db.execute(
            "SELECT value FROM meta WHERE key=?", ("review_validation:" + review_id,)
        ).fetchone()
        if not certificate or json.loads(certificate[0]).get("binding") != binding(
            record, parsed, report
        ):
            raise ValueError("Contrast validation binding changed")
        record["model_info"] = {
            k: v
            for k, v in json.loads(certificate[0]).items()
            if k in {"provider", "model", "prompt_version", "audit_provider", "audit_model"}
        }
        record["contrast"] = parsed.model_dump()
    return record, report


def corrections(db: sqlite3.Connection, config: Config, report_id: str) -> list[tuple[str, str]]:
    result = []
    for ident, result_id in db.execute(
        "SELECT id,result_id FROM review WHERE proposed_in_report=? AND contrast IS NOT NULL",
        (report_id,),
    ).fetchall():
        try:
            record, _ = read(db, config, ident)
            if record["contrast"]["summary_errors"]:
                result.append((ident, result_id))
        except (OSError, ValueError, sqlite3.Error):
            continue
    return result


def check_contrast(parsed: Contrast, report: Report, record: dict[str, Any]) -> None:
    validate(parsed, scope(report, record["result_id"]))
    fields = list(record["human_text"].values())
    for claim in parsed.unsupported + parsed.unverifiable:
        if not any(claim.text in field for field in fields):
            raise ValueError("Human quote is not present")


def binding(record: dict[str, Any], contrast: Contrast, report: Report) -> str:
    return content_hash(
        canonical(
            {
                "report": record["report_id"],
                "result": record["result_id"],
                "human": record["human_text"],
                "contrast": contrast.model_dump(),
                "evidence": [
                    asdict(e)
                    for e in report.evidence
                    if e.id in item(report, record["result_id"]).evidence
                ],
                "automatic_summary": report.sections.get("extract:" + record["result_id"]),
            }
        )
    )


def decide(
    db: sqlite3.Connection, config: Config, review_id: str, decision: str, doubt: str
) -> None:
    if decision not in {"closed", "needs_clarification", "postponed"}:
        raise ValueError("Unknown decision")
    clean = text_fields(config, "minimal", {"doubt": doubt})["doubt"]
    record, _ = read(db, config, review_id)
    if record["decision"] is not None:
        if record["decision"] == decision and record["doubts"] == ([clean] if clean else []):
            return
        raise ValueError("A decision has already been recorded")
    if not record["contrast"] and decision != "postponed":
        raise ValueError("Contrast is not ready")
    db.execute(
        "UPDATE review SET decision=?,decided_at=?,doubts=? WHERE id=? AND decision IS NULL",
        (decision, utc(datetime.now(UTC)), canonical([clean] if clean else []), review_id),
    )
    db.execute(
        "UPDATE result SET review_state=? WHERE id=?",
        ("closed_by_human" if decision == "closed" else decision, record["result_id"]),
    )
    enqueue(db, "deliver", {"review": review_id}, "web")


def retry(db: sqlite3.Connection, config: Config, review_id: str) -> None:
    record, _ = read(db, config, review_id)
    if record["decision"] or record["contrast"]:
        raise ValueError("Review no longer needs contrast")
    current = db.execute(
        "SELECT id,state FROM job WHERE kind='contrast' AND json_extract(params,'$.review')=? "
        "ORDER BY id DESC LIMIT 1",
        (review_id,),
    ).fetchone()
    if current and current[1] in {"queued", "running"}:
        return
    enqueue(db, "contrast", {"review": review_id}, "web")
