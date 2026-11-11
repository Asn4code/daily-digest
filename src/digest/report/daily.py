"""Build project understanding, daily orientation and an optional next focus."""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from digest.config import Config
from digest.llm.router import Task
from digest.report.activity import active_results, current_evidence_ids
from digest.report.context import attach_context, human_scope, prior_balance, weekly_focus
from digest.report.model import EvidenceEntry, Report

PROJECT_CHARS = 48_000
OVERVIEW_CHARS = 24_000
MAX_CANDIDATES = 40


class Generate(Protocol):
    def __call__(
        self,
        task: Task,
        key: str,
        ids: list[str],
        project_ids: set[str],
        context: dict[str, Any],
        result_ids: list[str],
        *,
        contract: str | None = None,
        prompt_name: str | None = None,
        wire_mode: str = "full",
        char_limit: int | None = None,
        cutoff: float | None = None,
    ) -> None: ...


def pending(report: Report, key: str, rule: str, category: str = "dependency") -> None:
    report.pending[key] = [
        {
            "stage": key.split(":", 1)[0],
            "section": key,
            "category": category,
            "rule": rule,
            "field": "$",
        }
    ]


def references(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        if "evidence" in value:
            ids = value["evidence"]
            refs.update(ids if isinstance(ids, list) else [ids])
        for item in value.values():
            refs.update(references(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(references(item))
    return refs


def fiche_view(report: Report, result_id: str) -> dict[str, Any]:
    fiche = report.sections["extract:" + result_id]
    output: dict[str, Any] = {
        "observations": [],
        "interpretations": [],
        "controls": [],
        "limitations": [],
        "open_questions": [],
    }
    seen: dict[str, set[str]] = {name: set() for name in output}
    for source in fiche["sources"]:
        values = {
            "observations": [source["summary"], *source["observations"]],
            "interpretations": source["interpretations"],
            "controls": source["controls"],
            "open_questions": source["open_questions"],
            "limitations": source["limitations"],
        }
        for name, entries in values.items():
            for value in entries:
                encoded = json.dumps(value, sort_keys=True, ensure_ascii=False)
                if encoded not in seen[name]:
                    seen[name].add(encoded)
                    output[name].append(value)
    return output


def task_evidence(db: sqlite3.Connection, project_id: str, task_id: str) -> EvidenceEntry | None:
    row = db.execute(
        "SELECT id,project_id,kind,locator,excerpt,observed_at,event_at,time_quality,meta,"
        "content_hash FROM evidence WHERE project_id=? AND task_id=? AND kind='task_transition' "
        "ORDER BY observed_at DESC,snapshot_id DESC,rowid DESC LIMIT 1",
        (project_id, task_id),
    ).fetchone()
    return (
        EvidenceEntry(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            json.loads(row[8]),
            row[9],
        )
        if row
        else None
    )


def frontier(
    db: sqlite3.Connection, config: Config, report: Report, tasks: dict[str, list[dict[str, Any]]]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], set[str]]:
    candidates: list[dict[str, Any]] = []
    states: dict[str, dict[str, str]] = {}
    auxiliary: set[str] = set()
    for project in sorted(config.projects, key=lambda p: (p.priority, p.id)):
        latest = db.execute(
            "SELECT status FROM snapshot WHERE project_id=? AND source='kanvas' "
            "ORDER BY id DESC LIMIT 1",
            (project.id,),
        ).fetchone()
        if not latest or latest[0] != "ok":
            continue
        available = sorted(
            (t for t in tasks.get(project.id, []) if t["state"] in {"todo", "doing"}),
            key=lambda t: (t["state"] != "doing", t["id"]),
        )
        known = {t["id"]: t["state"] for t in tasks.get(project.id, [])}
        for task in available:
            if len(candidates) >= MAX_CANDIDATES:
                report.warnings.append(
                    "El plan usa una frontera acotada; no evalúa todo el backlog."
                )
                break
            entry = task_evidence(db, project.id, task["id"])
            if not entry:
                continue
            attach_context(report, entry, config)
            auxiliary.add(entry.id)
            states.setdefault(project.id, {})[task["id"]] = task["state"]
            states[project.id].update({dep: known[dep] for dep in task["deps"] if dep in known})
            candidates.append({**task, "project_id": project.id, "evidence": [entry.id]})
    return candidates, states, auxiliary


def build(
    db: sqlite3.Connection,
    config: Config,
    report: Report,
    generate: Generate,
    tasks: dict[str, list[dict[str, Any]]],
    *,
    project_deadline: float,
    overview_deadline: float,
    deadline: float,
) -> None:
    planning_for = (
        datetime.fromisoformat(report.created_at).astimezone(ZoneInfo(config.timezone)).date()
        + timedelta(days=1)
    ).isoformat()
    report.human_context["planning_for"] = planning_for
    results = active_results(report)
    projects = {p.id: p for p in config.projects}
    by_project = {
        pid: [r for r in results if r.project == pid]
        for pid in sorted({r.project for r in results})
    }
    project_keys = []
    for index, (pid, items) in enumerate(by_project.items()):
        key = "project:" + pid
        project_keys.append(key)
        prior = prior_balance(db, config, report, pid)
        fiches = {r.id: fiche_view(report, r.id) for r in items}
        ids = references(fiches)
        current = current_evidence_ids(report)
        entries = {e.id: e for e in report.evidence}
        anchors = {
            max(
                set(r.evidence) & current,
                key=lambda eid: (entries[eid].event_at or entries[eid].observed_at, eid),
            )
            for r in items
            if set(r.evidence) & current
        }
        ids.update(anchors)
        ids.update(eid for r in items for eid in r.evidence if report.observations[eid]["computed"])
        if prior:
            ids.update(prior["evidence_ids"])
        generate(
            "conceptual",
            key,
            sorted(ids),
            {pid},
            {
                "project_id": pid,
                "objective": projects[pid].objective,
                "interval": {"start": report.start_at, "end": report.end_at},
                "fiches": fiches,
                "prior_balance": prior,
                "computed_observations": [
                    report.observations[eid]
                    for eid in sorted(ids)
                    if report.observations[eid]["computed"]
                ],
                "_parents": ["extract:" + r.id for r in items],
                "_wire_excerpt_ids": sorted(anchors),
                "_reference_evidence": prior["evidence_ids"] if prior else [],
                "_task_states": {
                    ident: state
                    for r in items
                    for ident, state in report.packages["extract:" + r.id]["task_states"].items()
                },
            },
            [r.id for r in items],
            contract="project",
            prompt_name="project",
            wire_mode="references",
            char_limit=PROJECT_CHARS,
            cutoff=min(
                project_deadline,
                time.monotonic()
                + max(0.0, project_deadline - time.monotonic()) / (len(by_project) - index),
            ),
        )
    if any(key not in report.sections for key in project_keys):
        pending(report, "conceptual", "project_balance_pending")
        pending(report, "plan", "project_balance_pending")
        return
    balances = {pid: report.sections["project:" + pid] for pid in by_project}
    ids = references(balances)
    generate(
        "conceptual",
        "conceptual",
        sorted(ids),
        set(by_project),
        {
            "balances": {
                pid: {k: v for k, v in balance.items() if k != "results"}
                for pid, balance in balances.items()
            },
            "interval": {"start": report.start_at, "end": report.end_at},
            "_parents": project_keys,
            "_task_states": {
                ident: state
                for key in project_keys
                for ident, state in report.packages[key]["task_states"].items()
            },
        },
        [r.id for r in results],
        wire_mode="references",
        char_limit=OVERVIEW_CHARS,
        cutoff=overview_deadline,
    )
    if "conceptual" not in report.sections:
        pending(report, "plan", "synthesis_pending")
        return
    if not report.human_context.get("scope_available", True):
        pending(report, "plan", "human_scope_missing", "input")
        return
    candidates, states, auxiliary = frontier(db, config, report, tasks)
    accepted = report.human_context.get("accepted_plan")
    scope = set(by_project) | {item["project_id"] for item in candidates}
    critical, critical_ids, critical_scope = weekly_focus(db, config, report)
    if critical and critical.get("unavailable"):
        pending(report, "plan", "weekly_scope_missing", "input")
        return
    if critical:
        report.human_context["weekly_focus"] = critical
        scope.update(critical_scope)
    if report.human_context.get("accepted_warmups"):
        warm_scope = human_scope(db, config)
        if warm_scope is None:
            pending(report, "plan", "human_scope_missing", "input")
            return
        scope.update(warm_scope)
    if accepted:
        scope.update(accepted["project_ids"])
        if accepted["project_id"] and accepted["kanvas_task_id"]:
            entry = task_evidence(db, accepted["project_id"], accepted["kanvas_task_id"])
            if entry:
                attach_context(report, entry, config)
                auxiliary.add(entry.id)
                status = next(
                    (
                        t["state"]
                        for t in tasks.get(accepted["project_id"], [])
                        if t["id"] == accepted["kanvas_task_id"]
                    ),
                    "blocked",
                )
                states.setdefault(accepted["project_id"], {})[accepted["kanvas_task_id"]] = status
    doubt_rows = db.execute(
        "SELECT v.result_id,v.doubts FROM review v JOIN result r "
        "ON r.id=v.result_id WHERE v.doubts!='[]' AND r.project_id IN ("
        + ",".join("?" for _ in scope)
        + ") AND v.id=(SELECT latest.id FROM review latest "
        "WHERE latest.result_id=v.result_id "
        "ORDER BY latest.submitted_at DESC,latest.id DESC LIMIT 1) "
        "ORDER BY v.submitted_at DESC,v.id DESC LIMIT ?",
        (*sorted(scope), MAX_CANDIDATES + 1),
    ).fetchall()
    if len(doubt_rows) > MAX_CANDIDATES:
        report.warnings.append("El plan usa las dudas vigentes más recientes; no toda la historia.")
    doubts = [
        {"result_id": row[0], "doubts": json.loads(row[1])} for row in doubt_rows[:MAX_CANDIDATES]
    ]
    if doubts:
        # Review prose may mention any configured project, including one whose
        # evidence is forbidden outside the internal provider.
        privacy_scope = human_scope(db, config)
        if privacy_scope is None:
            pending(report, "plan", "human_scope_missing", "input")
            return
        scope.update(privacy_scope)
    generate(
        "plan",
        "plan",
        sorted(ids | auxiliary | critical_ids),
        scope,
        {
            "orientation": report.sections["conceptual"],
            "balances": {
                pid: {k: v for k, v in balance.items() if k != "results"}
                for pid, balance in balances.items()
            },
            "objectives": {pid: projects[pid].objective for pid in scope},
            "task_candidates": candidates,
            "human_context": report.human_context,
            "human_doubts": doubts,
            "weekly_focus": critical,
            "planning_for": planning_for,
            "evidence_cutoff": report.end_at,
            "_project_task_states": states,
            "_task_states": {
                ident: state for items in states.values() for ident, state in items.items()
            },
            "_human_plan_ids": [accepted["id"]] if accepted else [],
            "_active_plan_id": accepted["id"]
            if accepted and accepted["availability"] == "available"
            else None,
            "_parents": [*project_keys, "conceptual"],
            "_auxiliary": sorted(auxiliary),
            "_reference_evidence": sorted(critical_ids),
        },
        [r.id for r in results],
        wire_mode="references",
        char_limit=PROJECT_CHARS,
        cutoff=deadline,
    )
