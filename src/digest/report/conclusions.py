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
    human_versions: dict[str, str] = {}
    human_checked: set[str] = set()
    automatic_latest: dict[str, tuple[dict[str, Any], dict[str, EvidenceEntry]]] = {}
    compared_evidence: dict[str, set[str]] = {}
    covered_latest: set[str] = set()

    def retain(item: dict[str, Any], originals: dict[str, EvidenceEntry]) -> None:
        rid = item["result_id"]
        if rid not in results or rid in chosen:
            return
        if item["author"] == "automatic":
            if ensure_human(rid):
                return
            automatic_latest.setdefault(rid, (dict(item), originals))
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
            covered_latest.add(rid)
            return
        if len(chosen) >= MAX_CONCLUSIONS:
            warning = "El contraste semanal prioriza veinte resultados con conclusiones previas."
            if warning not in report.warnings:
                report.warnings.append(warning)
            return
        identity = {
            key: value
            for key, value in item.items()
            if key not in {"privacy_projects", "human_decision", "model"}
        }
        item["id"] = "con_" + content_hash(canonical(identity))[:20]
        item["new_evidence"] = new
        item["review_state"] = results[rid].review_state
        if item["author"] == "automatic":
            later, later_sources = automatic_latest[rid]
            if later["version"] != item["version"]:
                item["later_automatic_interpretation"] = {
                    key: later[key]
                    for key in ("version", "text", "scope", "evidence", "source_date")
                }
                item["context_evidence"] = list(later["evidence"])
                item["privacy_projects"] = sorted(
                    set(item["privacy_projects"]) | set(later["privacy_projects"])
                )
                for eid in later["evidence"]:
                    attach_context(report, later_sources[eid], config)
        item = redact_tree(item, known_secrets(config))
        for eid in sorted(refs):
            attach_context(report, originals[eid], config)
        chosen[rid] = item
        covered_latest.discard(rid)

    # A human statement is its original submitted text, not a model's paraphrase
    # or an assertion that all its claims have been scientifically confirmed.
    rows = db.execute(
        "SELECT v.id,v.result_id,v.human_text,v.submitted_at,v.decision "
        "FROM review v JOIN result r ON r.id=v.result_id WHERE r.project_id=? "
        "AND v.human_text IS NOT NULL AND v.submitted_at<=? "
        "ORDER BY v.submitted_at DESC,v.id DESC LIMIT 40",
        (project_id, report.created_at),
    ).fetchall()

    def consider_human(row: tuple[Any, ...]) -> None:
        review_id, rid, text, submitted, decision = row
        if rid not in results or rid in chosen:
            return
        human_versions.setdefault(rid, review_id)
        if human_versions[rid] != review_id:
            return
        if len(text) > 12_000:
            report.warnings.append("Una explicación previa excede el límite del contraste semanal.")
            return
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
            return
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
                "privacy_projects": sorted(
                    {p.id for p in config.projects}
                    | {r[0] for r in db.execute("SELECT id FROM project")}
                ),
                "human_decision": decision,
                "source_report": None,
            },
            original,
        )

    def ensure_human(rid: str) -> bool:
        if rid not in human_checked:
            human_checked.add(rid)
            latest = db.execute(
                "SELECT id,result_id,human_text,submitted_at,decision FROM review "
                "WHERE result_id=? AND human_text IS NOT NULL AND submitted_at<=? "
                "ORDER BY submitted_at DESC,id DESC LIMIT 1",
                (rid, report.created_at),
            ).fetchone()
            if latest:
                consider_human(latest)
        return rid in human_versions

    for row in rows:
        human_checked.add(row[1])
        consider_human(row)

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
                if rid in results:
                    ensure_human(rid)
                compared_evidence.setdefault(rid, set()).update(check["new_evidence"])
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
                            item["privacy_projects"] = sorted(
                                set(item["privacy_projects"])
                                | set(previous.packages["critical:" + project_id]["project_ids"])
                            )
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
                        "privacy_projects": previous.packages["critical:" + project_id][
                            "project_ids"
                        ],
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
                            "privacy_projects": previous.packages["critical:" + project_id][
                                "project_ids"
                            ],
                            "human_decision": None,
                        },
                        original,
                    )
        project = previous.sections.get("project:" + project_id)
        if not project:
            continue
        for card in project["results"]:
            meaning = card["meaning"]
            statement_kind = "result_interpretation"
            if not meaning:
                candidate = project["importance"]
                owner_ids = [
                    r.id for r in previous.results if set(candidate["evidence"]) <= set(r.evidence)
                ]
                if owner_ids == [card["result_id"]]:
                    meaning = candidate
                    statement_kind = "project_importance"
            if not meaning:
                continue
            scope = {name: card[name] for name in ("question", "controls", "limits")}
            retain(
                {
                    "project_id": project_id,
                    "result_id": card["result_id"],
                    "text": meaning["text"],
                    "statement_kind": statement_kind,
                    "confidence": meaning["confidence"],
                    "scope": scope,
                    "evidence": sorted(references([meaning, scope])),
                    "source_date": previous.end_at,
                    "version": report_id,
                    "source_report": report_id,
                    "author": "automatic",
                    "privacy_projects": previous.packages["project:" + project_id]["project_ids"],
                    "model": previous.model_info.get("project:" + project_id, {}),
                    "human_decision": None,
                },
                original,
            )
    for rid, item in list(chosen.items()):
        item["new_evidence"] = sorted(set(item["new_evidence"]) - compared_evidence.get(rid, set()))
        if not item["new_evidence"]:
            del chosen[rid]
            covered_latest.add(rid)
    # All interval results remain in the report, even beyond this bounded history.
    report.human_context.setdefault("weekly_history", {})[project_id] = {
        "without_new_evidence": sorted(covered_latest),
        "comparison_results": sorted(chosen),
    }
    return list(chosen.values())
