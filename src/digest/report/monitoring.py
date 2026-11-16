"""Bounded evidence-backed monitoring of frozen human questions."""

import sqlite3
from typing import Any

from digest import watchlist
from digest.collectors.base import canonical, content_hash
from digest.config import Config
from digest.report.context import attach_context
from digest.report.daily import Generate, pending, references
from digest.report.loading import load_ready
from digest.report.model import Report

LABELS = {
    "news": "Novedades respaldadas",
    "no_new": "Sin novedades observadas",
    "insufficient": "Evidencia insuficiente",
    "source_pending": "Fuente pendiente",
    "coverage_failure": "Fallo de cobertura",
}
NOTICES = {
    "budget": "Pendiente: el tema no cabe en el paquete de preguntas de este informe.",
    "privacy": "Pendiente: falta una política de privacidad de un proyecto implicado.",
    "no_evidence": (
        "Pendiente: sin evidencias disponibles para evaluar este tema; "
        "no demuestra ausencia de trabajo."
    ),
    "generation": "Evaluación pendiente de generación y validación.",
}


def items(report: Report) -> list[dict[str, Any]]:
    return list(report.watchlist.get("items", []))


def eligible(report: Report, item: dict[str, Any]) -> bool:
    historical = set(report.human_context.get("watch_history", {}).get(item["id"], []))
    return item["omitted"] is None and any(
        e.project in item["projects"] and (not e.context_only or e.id in historical)
        for e in report.evidence
    )


def verify_snapshot(report: Report) -> None:
    if not report.watchlist:
        return  # Reports predating the feature have no monitoring section.
    payload = {k: v for k, v in report.watchlist.items() if k != "hash"}
    if (
        set(payload) != {"version", "items"}
        or payload["version"] != 1
        or content_hash(canonical(payload)) != report.watchlist.get("hash")
        or len(items(report)) > 30
        or len({s["id"] for s in items(report)}) != len(items(report))
    ):
        raise ValueError("Watchlist snapshot changed")
    remaining = 12000
    for item in items(report):
        value = watchlist.Item.model_validate(item["values"])
        if not watchlist.IDENT.fullmatch(item["id"]) or value.state != "active":
            raise ValueError("Invalid frozen watchlist item")
        if not re_revision(item["revision"]) or not item["projects"]:
            raise ValueError("Invalid frozen watchlist revision")
        if not set(item["projects"]) <= set(item["privacy_projects"]):
            raise ValueError("Watchlist privacy scope narrowed")
        if item["omitted"] not in {None, "budget", "privacy"}:
            raise ValueError("Invalid monitoring omission")
        if item["omitted"] is None:
            remaining -= len(value.title) + len(value.question)
            if remaining < 0:
                raise ValueError("Watchlist budget exceeded")


def re_revision(ident: str) -> bool:
    import re

    return re.fullmatch(r"nb_[a-f0-9]{32}", ident) is not None


def previous(
    db: sqlite3.Connection, config: Config, report: Report, item: dict[str, Any]
) -> tuple[dict[str, Any] | None, set[str], set[str]]:
    rows = db.execute(
        "SELECT r.id FROM report r JOIN interval i ON i.id=r.interval_id "
        "WHERE r.status='ready' AND i.end_at<=? AND i.kind=? "
        "ORDER BY i.end_at DESC,r.revision DESC LIMIT 3",
        (report.start_at, report.kind),
    ).fetchall()
    key = "watch:" + item["id"]
    for (ident,) in rows:
        try:
            prior, _, _ = load_ready(db, config, ident)
        except (OSError, ValueError):
            continue
        match = next((s for s in items(prior) if s["id"] == item["id"]), None)
        if match is None or match["revision"] != item["revision"] or key not in prior.sections:
            continue
        scope = set(prior.packages[key]["project_ids"])
        if not scope <= {p.id for p in config.projects}:
            return {"unavailable": True}, set(), scope
        value = prior.sections[key]
        ids = references(value)
        if len(ids) > 64:
            return None, set(), set()
        entries = {e.id: e for e in prior.evidence}
        if sum(len(entries[eid].excerpt) for eid in ids) > 48000:
            return None, set(), set()
        for eid in ids:
            attach_context(report, entries[eid], config)
        return (
            {
                "report_id": ident,
                "end_at": prior.end_at,
                "revision": item["revision"],
                "assessment": value,
                "status": "automatic_validated_not_human_acceptance",
            },
            ids,
            scope,
        )
    return None, set(), set()


def build(
    db: sqlite3.Connection, config: Config, report: Report, generate: Generate, *, deadline: float
) -> None:
    if not report.watchlist:
        report.watchlist = watchlist.freeze(db, config)
    verify_snapshot(report)
    configured = {p.id for p in config.projects}
    registered = {r[0] for r in db.execute("SELECT id FROM project")}
    for item in items(report):
        if item["omitted"]:
            continue
        key = "watch:" + item["id"]
        scope = set(item["privacy_projects"]) | configured | registered
        if not scope <= configured:
            pending(report, key, "watchlist_scope_missing", "input")
            continue
        prior, prior_ids, prior_scope = previous(db, config, report, item)
        if prior and prior.get("unavailable"):
            pending(report, key, "watchlist_history_scope_missing", "input")
            continue
        if prior_ids:
            report.human_context.setdefault("watch_history", {})[item["id"]] = sorted(prior_ids)
        if not eligible(report, item):
            continue
        ids = {e.id for e in report.evidence if e.project in item["projects"]}
        scope.update(prior_scope)
        coverage = [c for c in report.coverage if c.project in item["projects"]]
        complete = (
            bool(coverage)
            and set(item["projects"]) <= {c.project for c in coverage}
            and all(c.status == "ok" and not c.omitted for c in coverage)
        )
        from digest.report.activity import current_evidence_ids

        generate(
            "conceptual",
            key,
            sorted(ids | prior_ids),
            scope,
            {
                "watch_item": item,
                "interval": {"start": report.start_at, "end": report.end_at},
                "mode": "weekly_critical" if report.kind == "weekly" else "daily",
                "previous": prior,
                "coverage_complete": complete,
                "current_evidence_ids": sorted(ids & current_evidence_ids(report)),
                "_reference_evidence": sorted(prior_ids),
            },
            [r.id for r in report.results if r.project in item["projects"]],
            contract="watch",
            prompt_name="watchlist",
            char_limit=64000,
            cutoff=deadline,
        )


def view(report: Report) -> dict[str, Any]:
    entries = []
    for item in items(report):
        assessment = report.sections.get("watch:" + item["id"])
        reason = item["omitted"] or ("generation" if eligible(report, item) else "no_evidence")
        entries.append(
            {
                **item,
                "assessment": assessment,
                "label": LABELS[assessment["status"]] if assessment else NOTICES[reason],
            }
        )
    highlights = [
        e for e in entries if not e["assessment"] or e["assessment"]["status"] != "no_new"
    ][:3]
    return {
        "items": entries,
        "highlights": highlights,
        "total": len(entries),
        "pending": sum(not e["assessment"] for e in entries),
    }
