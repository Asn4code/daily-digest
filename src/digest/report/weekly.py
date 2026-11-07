"""Critical weekly comparisons before orientation and proposed objectives."""

import sqlite3
import time
from typing import Any

from digest.config import Config
from digest.report.activity import active_results, current_evidence_ids
from digest.report.conclusions import baselines
from digest.report.daily import Generate, fiche_view, pending, references
from digest.report.model import Report


def build(
    db: sqlite3.Connection,
    config: Config,
    report: Report,
    generate: Generate,
    tasks: dict[str, list[dict[str, Any]]],
    *,
    critical_deadline: float,
    deadline: float,
) -> None:
    results = active_results(report)
    projects = {p.id: p for p in config.projects}
    by_project = {
        pid: [r for r in results if r.project == pid]
        for pid in sorted({r.project for r in results})
    }
    all_prior: dict[str, dict[str, Any]] = {}
    keys = []
    report.human_context["weekly_conclusions"] = []
    for index, (pid, items) in enumerate(by_project.items()):
        prior = baselines(db, config, report, pid)
        all_prior.update({p["id"]: p for p in prior})
        report.human_context["weekly_conclusions"].extend(prior)
        fiches = {r.id: fiche_view(report, r.id) for r in items}
        ids = references(fiches) | {eid for p in prior for eid in p["evidence"]}
        ids.update(eid for p in prior for eid in p.get("context_evidence", []))
        entries = {e.id: e for e in report.evidence}
        current = current_evidence_ids(report)
        anchors = {
            max(
                set(r.evidence) & current,
                key=lambda eid: (entries[eid].event_at or entries[eid].observed_at, eid),
            )
            for r in items
            if set(r.evidence) & current
        }
        ids.update(anchors)
        ids.update(eid for p in prior for eid in p["new_evidence"])
        # Human prose may mention other projects. Conservatively apply every
        # configured privacy policy, as with an edited accepted plan.
        scope = set(projects) if any(p["author"] == "human" for p in prior) else {pid}
        key = "critical:" + pid
        keys.append(key)
        generate(
            "weekly",
            key,
            sorted(ids),
            scope,
            {
                "project_id": pid,
                "objective": projects[pid].objective,
                "fiches": fiches,
                "interval": {"start": report.start_at, "end": report.end_at},
                "history_limits": list(report.warnings),
                "_conclusions": {p["id"]: p for p in prior},
                "_parents": ["extract:" + r.id for r in items],
                "_reference_evidence": sorted(
                    {eid for p in prior for eid in (p["evidence"] + p.get("context_evidence", []))}
                ),
                "_wire_excerpt_ids": sorted(anchors),
                "_task_states": {},
            },
            [r.id for r in items],
            contract="critical",
            prompt_name="critical",
            wire_mode="references",
            char_limit=48_000,
            cutoff=min(
                critical_deadline,
                time.monotonic()
                + max(0.0, critical_deadline - time.monotonic()) / (len(by_project) - index),
            ),
        )
    if any(key not in report.sections for key in keys):
        pending(report, "weekly", "critical_stage_pending")
        return
    critical = {c["conclusion_id"]: c for key in keys for c in report.sections[key]["checks"]}
    ids = {e["id"] for key in keys for e in report.packages[key]["evidence"]}
    figures = {e.id for e in report.evidence if e.kind == "figure" and not e.context_only}
    ids.update(figures)
    present = {e.project for e in report.evidence}
    marks = ",".join("?" for _ in present)
    parameters = tuple(sorted(present))
    completed = sorted(
        {
            row[0]
            for row in db.execute(
                "SELECT v.result_id FROM review v JOIN result r ON r.id=v.result_id "
                "WHERE v.decision='closed' AND v.decided_at>=? AND v.decided_at<=? "
                "AND r.project_id IN (" + marks + ")",
                (report.start_at, report.end_at, *parameters),
            )
        }
    )
    reviews_pending = [
        row[0]
        for row in db.execute(
            "SELECT id FROM result WHERE review_state!='closed_by_human' AND first_seen_at<=? "
            "AND project_id IN (" + marks + ") ORDER BY first_seen_at,id",
            (report.end_at, *parameters),
        )
    ]
    accepted = [
        dict(zip(["action", "done_criterion", "edited_text"], row, strict=True))
        for row in db.execute(
            "SELECT p.action,p.done_criterion,p.edited_text FROM plan_item p "
            "JOIN report r ON r.id=p.report_id JOIN interval i ON i.id=r.interval_id "
            "WHERE p.accepted=1 AND i.end_at>=? AND i.end_at<=? ORDER BY i.end_at,p.id LIMIT 100",
            (report.start_at, report.end_at),
        )
    ]
    scope = (
        set(projects)
        if accepted or any(p["author"] == "human" for p in all_prior.values())
        else present
    )
    states = {pid: {t["id"]: t["state"] for t in items} for pid, items in tasks.items()}
    generate(
        "weekly",
        "weekly",
        sorted(ids),
        scope,
        {
            "objectives": {pid: projects[pid].objective for pid in present},
            "project_balances": {pid: report.sections["critical:" + pid] for pid in by_project},
            "completed_reviews": completed,
            "pending_reviews": reviews_pending,
            "accepted_plans": accepted,
            "_conclusions": all_prior,
            "_critical": critical,
            "_parents": keys,
            "_reference_evidence": sorted(
                figures - {e["id"] for key in keys for e in report.packages[key]["evidence"]}
            ),
            "_project_task_states": states,
        },
        [r.id for r in report.results],
        wire_mode="references",
        char_limit=64_000,
        cutoff=deadline,
    )
