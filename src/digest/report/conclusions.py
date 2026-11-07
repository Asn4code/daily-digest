"""Versioned prior statements with original evidence, author and human status."""

import json
import sqlite3
from typing import Any

from digest.collectors.base import canonical, content_hash
from digest.config import Config
from digest.report.activity import active_results, current_evidence_ids
from digest.report.context import attach_context
from digest.report.daily import references
from digest.report.loading import load_ready
from digest.report.model import EvidenceEntry, Report
from digest.util.redact import known_secrets, redact_tree

MAX_CONCLUSIONS = 20
MAX_PRIOR_EVIDENCE = 200


def baselines(
    db: sqlite3.Connection, config: Config, report: Report, project_id: str
) -> list[dict[str, Any]]:
    results = {r.id: r for r in active_results(report) if r.project == project_id}
    entries = {e.id: e for e in report.evidence}
    current = current_evidence_ids(report)
    chosen: dict[str, dict[str, Any]] = {}

    def retain(item: dict[str, Any], originals: dict[str, EvidenceEntry]) -> None:
        rid = item["result_id"]
        refs = set(item["evidence"])
        if rid not in results or rid in chosen or not refs or not refs <= originals.keys():
            return
        if any(originals[eid].project != project_id for eid in refs):
            return
        new = sorted(
            eid
            for eid in results[rid].evidence
            if eid in current
            and eid not in refs
            and (entries[eid].event_at or entries[eid].observed_at) > item["source_date"]
        )
        if not new:
            return
        if len(chosen) >= MAX_CONCLUSIONS:
            warning = "El contraste semanal prioriza veinte resultados con conclusiones previas."
            if warning not in report.warnings:
                report.warnings.append(warning)
            return
        item["id"] = "con_" + content_hash(canonical(item))[:20]
        item["new_evidence"] = new
        item["review_state"] = results[rid].review_state
        item = redact_tree(item, known_secrets(config))
        for eid in sorted(refs):
            attach_context(report, originals[eid], config)
        chosen[rid] = item

    # A human statement is its original submitted text, not a model's paraphrase
    # or an assertion that all its claims have been scientifically confirmed.
    rows = db.execute(
        "SELECT v.id,v.result_id,v.human_text,v.submitted_at,v.decision "
        "FROM review v JOIN result r ON r.id=v.result_id WHERE r.project_id=? "
        "AND v.human_text IS NOT NULL AND v.submitted_at<? "
        "ORDER BY v.submitted_at DESC,v.id DESC LIMIT 40",
        (project_id, report.end_at),
    ).fetchall()
    for review_id, rid, text, submitted, decision in rows:
        if rid not in results or rid in chosen:
            continue
        if len(text) > 12_000:
            report.warnings.append("Una explicación previa excede el límite del contraste semanal.")
            continue
        rows_e = db.execute(
            "SELECT e.id,e.project_id,e.kind,e.locator,e.excerpt,e.observed_at,e.event_at,"
            "e.time_quality,e.meta,e.content_hash FROM result_evidence re "
            "JOIN evidence e ON e.id=re.evidence_id WHERE re.result_id=? "
            "AND COALESCE(e.event_at,e.observed_at)<=? AND e.observed_at<=? "
            "ORDER BY e.id LIMIT ?",
            (rid, submitted, submitted, MAX_PRIOR_EVIDENCE + 1),
        ).fetchall()
        if len(rows_e) > MAX_PRIOR_EVIDENCE:
            report.warnings.append("Fuentes de una revisión previa exceden el límite semanal.")
            continue
        original = {
            r[0]: EvidenceEntry(
                r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], json.loads(r[8]), r[9]
            )
            for r in rows_e
        }
        retain(
            {
                "project_id": project_id,
                "result_id": rid,
                "text": text,
                "scope": (
                    "Explicación humana íntegra del resultado; "
                    "sus dudas no son conclusiones confirmadas."
                ),
                "evidence": sorted(original),
                "source_date": submitted,
                "version": review_id,
                "author": "human",
                "human_decision": decision,
                "source_report": None,
            },
            original,
        )

    rows_r = db.execute(
        "SELECT DISTINCT r.id FROM report r JOIN interval i ON r.interval_id=i.id "
        "JOIN report_evidence re ON re.report_id=r.id JOIN evidence e ON e.id=re.evidence_id "
        "WHERE r.status='ready' AND i.end_at<? AND e.project_id=? "
        "ORDER BY i.end_at DESC,r.revision DESC LIMIT 8",
        (report.end_at, project_id),
    ).fetchall()
    for (report_id,) in rows_r:
        try:
            previous, _, _ = load_ready(db, config, report_id)
        except (ValueError, OSError):
            continue
        original = {e.id: e for e in previous.evidence}
        critical = previous.sections.get("critical:" + project_id)
        if critical:
            old_statements = {
                p["id"]: p for p in previous.human_context.get("weekly_conclusions", [])
            }
            for check in critical["checks"]:
                old = old_statements[check["conclusion_id"]]
                rid = old["result_id"]
                if rid in chosen:
                    item = chosen[rid]
                    if item["version"] == old["version"] and not item.get("previous_comparisons"):
                        refs = references(check)
                        if refs <= original.keys() and all(
                            original[e].project == project_id for e in refs
                        ):
                            item["previous_comparisons"] = [
                                {
                                    "version": report_id,
                                    "date": previous.end_at,
                                    "outcome": check["outcome"],
                                    "assessment": check["assessment"],
                                    "decisive_limit": check["decisive_limit"],
                                    "comparability": check["comparability"],
                                }
                            ]
                            item["context_evidence"] = sorted(refs)
                            for eid in sorted(refs):
                                attach_context(report, original[eid], config)
                    continue
                retain(
                    {
                        "project_id": project_id,
                        "result_id": rid,
                        "text": check["assessment"]["text"],
                        "confidence": check["assessment"]["confidence"],
                        "scope": {
                            "original_statement": old["text"],
                            "original_scope": old["scope"],
                            "comparability": check["comparability"],
                            "limit": check["decisive_limit"],
                        },
                        "evidence": sorted(
                            references(
                                [
                                    check["assessment"],
                                    check["comparability"],
                                    check["decisive_limit"],
                                ]
                            )
                        ),
                        "source_date": previous.end_at,
                        "version": report_id,
                        "source_report": report_id,
                        "author": "automatic",
                        "human_decision": None,
                    },
                    original,
                )
            for hypothesis in critical["hypotheses_changed"]:
                owners = [
                    r
                    for r in previous.results
                    if r.id in results and set(hypothesis["evidence"]) <= set(r.evidence)
                ]
                if len(owners) == 1:
                    rid = owners[0].id
                    sources = previous.sections.get("extract:" + rid, {}).get("sources", [])
                    scope = {
                        "controls": [c for s in sources for c in s["controls"]],
                        "limits": [c for s in sources for c in s["limitations"]],
                    }
                    retain(
                        {
                            "project_id": project_id,
                            "result_id": rid,
                            "text": hypothesis["text"],
                            "confidence": hypothesis["confidence"],
                            "scope": scope,
                            "evidence": sorted(references([hypothesis, scope])),
                            "source_date": previous.end_at,
                            "version": report_id,
                            "source_report": report_id,
                            "author": "automatic",
                            "human_decision": None,
                        },
                        original,
                    )
        project = previous.sections.get("project:" + project_id)
        if not project:
            continue
        for card in project["results"]:
            meaning = card["meaning"]
            if not meaning:
                continue
            scope = {name: card[name] for name in ("question", "controls", "limits")}
            retain(
                {
                    "project_id": project_id,
                    "result_id": card["result_id"],
                    "text": meaning["text"],
                    "confidence": meaning["confidence"],
                    "scope": scope,
                    "evidence": sorted(references([meaning, scope])),
                    "source_date": previous.end_at,
                    "version": report_id,
                    "source_report": report_id,
                    "author": "automatic",
                    "model": previous.model_info.get("project:" + project_id, {}),
                    "human_decision": None,
                },
                original,
            )
    # All interval results remain in the report, even beyond this bounded history.
    return list(chosen.values())
