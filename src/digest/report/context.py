"""Bounded human intent and prior context, kept separate from new observations."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from pydantic import TypeAdapter

from digest.config import Config
from digest.report.loading import load_ready
from digest.report.model import EvidenceEntry, Report
from digest.report.observations import normalize
from digest.util.redact import known_secrets, redact_tree


def human_scope(db: sqlite3.Connection, config: Config) -> set[str] | None:
    """Free human prose may mention projects removed from the current config."""
    configured = {p.id for p in config.projects}
    registered = {row[0] for row in db.execute("SELECT id FROM project")}
    return configured if registered <= configured else None


def human_context(
    db: sqlite3.Connection, config: Config, tasks: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    row = db.execute(
        "SELECT p.id,p.report_id,p.action,p.done_criterion,p.dependency,"
        "p.edited_text,p.reason,p.origin,"
        "p.kanvas_task_id,i.end_at FROM plan_item p JOIN report r ON r.id=p.report_id "
        "JOIN interval i ON i.id=r.interval_id WHERE p.accepted=1 AND p.kind='mission' "
        "ORDER BY i.end_at DESC,r.revision DESC,p.id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {"accepted_plan": None, "accepted_warmups": [], "scope_available": True}
    plan = dict(
        zip(
            [
                "id",
                "report_id",
                "action",
                "done_criterion",
                "dependency",
                "edited_text",
                "reason",
                "origin",
                "kanvas_task_id",
                "source_date",
            ],
            row,
            strict=True,
        )
    )
    scope_row = db.execute(
        "SELECT value FROM meta WHERE key=?", (f"plan_scope:{row[0]}",)
    ).fetchone()
    scope = (
        set(json.loads(scope_row[0]))
        if scope_row
        else {
            r[0]
            for r in db.execute(
                "SELECT DISTINCT e.project_id FROM report_evidence re "
                "JOIN evidence e ON e.id=re.evidence_id WHERE re.report_id=?",
                (row[1],),
            )
        }
    )
    if plan["edited_text"] is not None or not scope:
        scope.update(r[0] for r in db.execute("SELECT id FROM project"))
    configured = {p.id for p in config.projects}
    if not scope <= configured:
        return {
            "accepted_plan": None,
            "accepted_warmups": [],
            "scope_available": False,
            "unavailable_reason": "El plan aceptado incluye un proyecto fuera de la configuración.",
        }
    project_row = db.execute(
        "SELECT value FROM meta WHERE key=?", (f"plan_project:{row[0]}",)
    ).fetchone()
    project_id = project_row[0] if project_row else next(iter(scope)) if len(scope) == 1 else None
    plan.update(project_id=project_id, project_ids=sorted(scope), availability="available")
    if plan["origin"] == "kanvas":
        candidates = [
            t["state"]
            for pid, items in tasks.items()
            if project_id is None or pid == project_id
            for t in items
            if t["id"] == plan["kanvas_task_id"]
        ]
        if len(candidates) != 1 or candidates[0] in {"done", "review", "blocked"}:
            plan["availability"] = "unavailable_task"
    warmups = [
        dict(zip(["id", "action", "done_criterion", "edited_text"], item, strict=True))
        for item in db.execute(
            "SELECT id,action,done_criterion,edited_text FROM plan_item "
            "WHERE report_id=? AND accepted=1 AND kind='warmup' ORDER BY id LIMIT 2",
            (row[1],),
        )
    ]
    result: dict[str, Any] = {
        "accepted_plan": plan,
        "accepted_warmups": warmups,
        "scope_available": True,
    }
    result = redact_tree(result, known_secrets(config))
    return result


def attach_context(report: Report, entry: EvidenceEntry, config: Config) -> None:
    if any(e.id == entry.id for e in report.evidence):
        return
    copied = deepcopy(entry)
    copied.context_only = True
    copied.meta["report_role"] = "supporting_context"
    copied = TypeAdapter(EvidenceEntry).validate_python(
        redact_tree(asdict(copied), known_secrets(config))
    )
    report.evidence.append(copied)
    report.observations[copied.id] = normalize(copied)


def prior_balance(
    db: sqlite3.Connection, config: Config, report: Report, project_id: str
) -> dict[str, Any] | None:
    rows = db.execute(
        "SELECT DISTINCT r.id,i.end_at FROM report r JOIN interval i ON i.id=r.interval_id "
        "JOIN report_evidence re ON re.report_id=r.id JOIN evidence e ON e.id=re.evidence_id "
        "WHERE r.status='ready' AND i.kind IN ('daily','preview') AND i.end_at<=? "
        "AND e.project_id=? ORDER BY i.end_at DESC,r.revision DESC LIMIT 3",
        (report.start_at, project_id),
    ).fetchall()
    for report_id, end in rows:
        try:
            previous, _, _ = load_ready(db, config, report_id)
        except (ValueError, OSError):
            continue
        key = "project:" + project_id
        if key not in previous.sections:
            continue
        balance = deepcopy(previous.sections[key])
        # Brief integration, with every stated limitation; detailed result cards
        # remain available in the original immutable report.
        balance.pop("results", None)
        references: set[str] = set()

        def refs(value: Any, found: set[str] = references) -> None:
            if isinstance(value, dict):
                if "evidence" in value:
                    ids = value["evidence"]
                    found.update(ids if isinstance(ids, list) else [ids])
                for child in value.values():
                    refs(child, found)
            elif isinstance(value, list):
                for child in value:
                    refs(child, found)

        refs(balance)
        entries = {e.id: e for e in previous.evidence}
        if not references <= entries.keys() or any(
            entries[eid].project != project_id for eid in references
        ):
            continue
        for eid in sorted(references):
            attach_context(report, entries[eid], config)
        report.human_context.setdefault("prior_reports", []).append(
            {"id": report_id, "project": project_id, "end_at": end}
        )
        return {
            "source_report": report_id,
            "end_at": end,
            "status": "automatic_validated_not_human_acceptance",
            "balance": balance,
            "evidence_ids": sorted(references),
        }
    return None
