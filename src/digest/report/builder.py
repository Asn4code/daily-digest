"""Generate validated sections while retaining every pending inventory item."""

import json
import sqlite3
import time
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel

from digest.collectors.store import previous_payload
from digest.config import Config
from digest.llm import schemas
from digest.llm.prompts import load, messages
from digest.llm.router import Router, Task
from digest.llm.validator import EvidencePackage, validate
from digest.report.assembly import VERSION as ASSEMBLY_VERSION
from digest.report.assembly import assemble
from digest.report.model import EvidenceEntry, Report, ResultEntry
from digest.report.observations import normalize
from digest.report.packets import SOURCE_PACKET_CHARS, Packet
from digest.report.packets import plan as plan_packets
from digest.util.redact import known_secrets, redact, redact_tree

SCHEMAS: dict[str, type[BaseModel]] = {
    "extract": schemas.ResultExtraction,
    "source": schemas.SourceFindings,
    "conceptual": schemas.DailySynthesis,
    "plan": schemas.TomorrowPlan,
    "weekly": schemas.WeeklyReport,
}


def task_context(db: sqlite3.Connection, config: Config) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for project in config.projects:
        tasks = (previous_payload(db, project.id, "kanvas") or {}).get("tasks", {})
        states = {ident: t["state"] for ident, t in tasks.items()}
        result[project.id] = [
            {
                "id": ident,
                "title": t["title"],
                "state": (
                    "blocked"
                    if t["state"] == "todo"
                    and any(states.get(d) != "done" for d in t.get("deps", []))
                    else t["state"]
                ),
                "deps": t.get("deps", []),
            }
            for ident, t in tasks.items()
        ]
    return result


def package_scope(payload: dict[str, Any]) -> EvidencePackage:
    entries = {e["id"]: EvidenceEntry(**e) for e in payload["evidence"]}
    return EvidencePackage(
        entries,
        set(payload["project_ids"]),
        set(payload.get("result_ids", [])),
        payload.get("task_states", {}),
        set(payload.get("completed_reviews", [])),
        list(payload.get("pending_reviews", [])),
    )


def enrich(db: sqlite3.Connection, config: Config, report: Report, router: Router) -> Report:
    # Rebuild generation state from revalidated nodes; never inherit a stale success
    # or rejection after inputs/configuration changed. Human state lives elsewhere.
    for generated in (
        report.sections,
        report.packages,
        report.model_info,
        report.prompt_versions,
        report.pending,
        report.source_units,
    ):
        generated.clear()
    report.warnings.clear()
    secrets = known_secrets(config)
    for item in report.evidence:
        item.excerpt = redact(item.excerpt, secrets)
        item.locator = redact(item.locator, secrets)
        item.meta = redact_tree(item.meta, secrets)
    for result in report.results:
        result.title = redact(result.title, secrets)
        for figure in result.figures:
            figure.caption = redact(figure.caption, secrets)
    for coverage in report.coverage:
        coverage.omitted = redact_tree(coverage.omitted, secrets)
    for thread in report.open_threads:
        thread.text = redact(thread.text, secrets)
    tasks = task_context(db, config)
    projects = {p.id: p for p in config.projects}
    evidence = {e.id: e for e in report.evidence}
    started = time.monotonic()
    duration = max(0.0, router.deadline - started)
    source_deadline = started + duration * 0.65
    synthesis_deadline = started + duration * 0.85
    source_calls_remaining = 1
    report.observations = {e.id: normalize(e) for e in report.evidence}

    def mark_pending(key: str, category: str, rule: str) -> None:
        report.pending[key] = [
            {
                "stage": key.split(":", 1)[0],
                "section": key,
                "category": category,
                "rule": rule,
                "field": "$",
            }
        ]

    def payload_for(
        ids: list[str], project_ids: set[str], context: dict[str, Any], result_ids: list[str]
    ) -> dict[str, Any]:
        if any(evidence[eid].project not in project_ids for eid in ids):
            raise ValueError("Evidence outside project scope")
        scoped_tasks = [t for pid in project_ids for t in tasks.get(pid, [])]
        states: dict[str, str] = {}
        for task_item in scoped_tasks:
            ident = task_item["id"]
            states[ident] = "blocked" if ident in states else task_item["state"]
        payload: dict[str, Any] = {
            "project_ids": sorted(project_ids),
            "result_ids": result_ids,
            "task_states": states,
            "context": {
                **context,
                "coverage": [
                    {
                        "source": c.source,
                        "status": c.status,
                        "omission_reasons": sorted({item["reason"] for item in c.omitted}),
                    }
                    for c in report.coverage
                    if c.project in project_ids
                ],
            },
            "completed_reviews": context.get("completed_reviews", []),
            "pending_reviews": context.get("pending_reviews", []),
            "evidence": [],
        }
        for eid in sorted(set(ids)):
            item = asdict(evidence[eid])
            item["meta"] = {
                k: v
                for k, v in item["meta"].items()
                if k
                in {
                    "stats",
                    "change",
                    "path",
                    "provenance",
                    "capture_origin",
                    "stored_outputs_only",
                    "report_role",
                }
            }
            payload["evidence"].append(item)
        payload = redact_tree(payload, secrets)
        return payload

    def call(
        task: Task,
        key: str,
        ids: list[str],
        project_ids: set[str],
        context: dict[str, Any],
        result_ids: list[str],
        *,
        source: bool = False,
    ) -> None:
        if not ids or not project_ids:
            mark_pending(key, "input", "no_evidence")
            return
        prompt = load(task, name="source" if source else None)
        limit = config.limits.max_project_package_chars * len(project_ids)
        if source:
            limit = min(limit, SOURCE_PACKET_CHARS)
        payload = payload_for(ids, project_ids, context, result_ids)
        if source:
            payload["task_states"] = (
                {context["task_id"]: "context"} if context.get("task_id") else {}
            )
            payload["context"]["computed_facts"] = [
                {"evidence": [eid], "computed": report.observations[eid]["computed"]}
                for eid in sorted(set(ids))
                if report.observations[eid]["computed"]
            ]
            if len(json.dumps(messages(prompt, payload), ensure_ascii=False)) > limit:
                mark_pending(key, "input", "coherent_unit_budget_exceeded")
                return
        else:
            items = payload["evidence"]
            payload["evidence"] = []
            if len(json.dumps(messages(prompt, payload), ensure_ascii=False)) > limit:
                mark_pending(key, "input", "context_budget_exceeded")
                return
            priority = {
                "task_note": 0,
                "metric": 1,
                "task_transition": 2,
                "run_error": 3,
                "diff": 4,
            }
            if task == "weekly":
                priority["figure"] = 0
            for item in sorted(items, key=lambda e: priority.get(e["kind"], 5)):
                payload["evidence"].append(item)
                if len(json.dumps(messages(prompt, payload), ensure_ascii=False)) > limit:
                    payload["evidence"].pop()
                    report.warnings.append(
                        key + ": evidencia omitida por límite de paquete (" + item["id"] + ")."
                    )
            if not payload["evidence"]:
                mark_pending(key, "input", "evidence_budget_exceeded")
                return
        scope = package_scope(payload)
        schema = schemas.SourceFindings if source else SCHEMAS[task]

        def check(value: dict[str, Any]) -> BaseModel:
            parsed = schema.model_validate(value)
            validate(parsed, scope)
            return parsed

        before = len(router.issues)
        eligible = [
            name
            for name in getattr(config.llm.routing, task)
            if name == "internal" or all(projects[pid].external_allowed for pid in project_ids)
        ]
        # A fair share alone can make every slow but valid node time out, leaving
        # nothing reusable. Allow bounded progress, then continue in another attempt.
        allowance = max(
            max(0.0, source_deadline - time.monotonic()) / max(1, source_calls_remaining),
            min(duration * 0.2, sum(config.llm.providers[name].timeout_s for name in eligible)),
        )
        response = router.generate(
            task,
            project_ids=project_ids,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            messages=messages(prompt, payload),
            schema=schema.model_json_schema(),
            validate=check,
            section=key,
            package=payload,
            deadline=(
                min(
                    source_deadline,
                    time.monotonic() + allowance,
                )
                if source
                else synthesis_deadline
                if task == "conceptual"
                else router.deadline
            ),
        )
        if response is None:
            report.pending[key] = router.issues[before:] or [
                {
                    "stage": task,
                    "section": key,
                    "category": "provider",
                    "rule": "no_eligible_provider",
                    "field": "$",
                }
            ]
            return
        report.sections[key] = response.value.model_dump()
        report.packages[key] = payload
        report.model_info[key] = {
            "provider": response.provider,
            "model": response.model,
            "cache_key": response.cache_key,
            "reused": str(response.reused).lower(),
        }
        report.prompt_versions[key] = response.prompt_version

    planned: list[tuple[ResultEntry, dict[str, Any], list[Packet]]] = []
    for result in report.results:
        context: dict[str, Any] = {
            "result_id": result.id,
            "title": result.title,
            "task_id": result.task_id,
            "objective": projects[result.project].objective,
            "external_allowed": projects[result.project].external_allowed,
        }

        def size(
            ids: list[str], result: ResultEntry = result, context: dict[str, Any] = context
        ) -> int:
            payload = payload_for(ids, {result.project}, context, [result.id])
            payload["task_states"] = (
                {context["task_id"]: "context"} if context.get("task_id") else {}
            )
            payload["context"]["computed_facts"] = [
                {"evidence": [eid], "computed": report.observations[eid]["computed"]}
                for eid in sorted(set(ids))
                if report.observations[eid]["computed"]
            ]
            return len(
                json.dumps(messages(load("extract", name="source"), payload), ensure_ascii=False)
            )

        packets = plan_packets(
            [evidence[eid] for eid in result.evidence],
            size=size,
            limit=min(SOURCE_PACKET_CHARS, config.limits.max_project_package_chars),
        )
        planned.append((result, context, packets))
    source_calls_remaining = max(1, sum(len(packets) for _, _, packets in planned))
    for result, context, packets in planned:
        keys = ["source:" + result.id + ":" + packet.key for packet in packets]
        report.source_units[result.id] = keys
        for packet, key in zip(packets, keys, strict=True):
            if not packet.fits:
                mark_pending(key, "input", "coherent_unit_budget_exceeded")
                source_calls_remaining -= 1
                continue
            call(
                "extract", key, packet.evidence, {result.project}, context, [result.id], source=True
            )
            source_calls_remaining -= 1
        root = "extract:" + result.id
        if not keys or any(key not in report.sections for key in keys):
            mark_pending(root, "dependency", "source_pending")
            continue
        findings = [schemas.SourceFindings.model_validate(report.sections[key]) for key in keys]
        payload = payload_for(
            result.evidence, {result.project}, {"assembled_from": keys}, [result.id]
        )
        try:
            extracted = assemble(result.id, findings)
            validate(extracted, package_scope(payload))
        except ValueError:
            mark_pending(root, "input", "assembly_contract_limit")
            continue
        report.sections[root] = extracted.model_dump()
        report.packages[root] = payload
        report.model_info[root] = {"provider": "assembly", "model": "validated-sources"}
        report.prompt_versions[root] = ASSEMBLY_VERSION
    # Downstream synthesis must never turn a partial extraction set into a final story.
    if any("extract:" + item.id not in report.sections for item in report.results):
        for key in ["weekly"] if report.kind == "weekly" else ["conceptual", "plan"]:
            mark_pending(key, "dependency", "extraction_pending")
        report.mechanical = not bool(report.sections)
        return report
    if not evidence:
        report.mechanical = False
        return report
    present = {e.project for e in report.evidence}
    results = [r.id for r in report.results]
    context = {
        "objectives": {pid: projects[pid].objective for pid in present},
        "results": [{"id": r.id, "project": r.project, "title": r.title} for r in report.results],
        "extractions": {
            key: value for key, value in report.sections.items() if key.startswith("extract:")
        },
    }
    if report.kind != "weekly":
        call("conceptual", "conceptual", list(evidence), present, context, results)
        if present and "conceptual" not in report.sections:
            mark_pending("plan", "dependency", "synthesis_pending")
            report.mechanical = not bool(report.sections)
            return report
        human_doubts = [
            {"result_id": r[0], "doubts": json.loads(r[1])}
            for r in db.execute(
                "SELECT v.result_id,v.doubts FROM review v JOIN result r ON r.id=v.result_id "
                "WHERE v.doubts!='[]' AND r.project_id IN ("
                + ",".join("?" for _ in present)
                + ") ORDER BY v.submitted_at",
                tuple(sorted(present)),
            )
        ]
        call(
            "plan",
            "plan",
            list(evidence),
            present,
            {
                "synthesis": report.sections.get("conceptual"),
                "tasks": {pid: tasks.get(pid, []) for pid in present},
                "human_doubts": human_doubts,
            },
            results,
        )
    elif present:
        marks = ",".join("?" for _ in present)
        parameters = tuple(sorted(present))
        completed = sorted(
            {
                r[0]
                for r in db.execute(
                    "SELECT v.result_id FROM review v JOIN result r ON r.id=v.result_id "
                    "WHERE v.decision='closed' AND v.decided_at>=? AND v.decided_at<=? "
                    "AND r.project_id IN (" + marks + ")",
                    (report.start_at, report.end_at, *parameters),
                )
            }
        )
        pending = [
            r[0]
            for r in db.execute(
                "SELECT id FROM result WHERE review_state!='closed_by_human' "
                "AND first_seen_at<=? AND project_id IN (" + marks + ") ORDER BY first_seen_at,id",
                (report.end_at, *parameters),
            )
        ]
        accepted = [
            dict(zip(["action", "done_criterion", "edited_text"], row, strict=True))
            for row in db.execute(
                "SELECT p.action,p.done_criterion,p.edited_text FROM plan_item p "
                "JOIN report r ON r.id=p.report_id JOIN interval i ON i.id=r.interval_id "
                "WHERE p.accepted=1 AND i.end_at>=? AND i.end_at<=? ORDER BY i.end_at,p.id",
                (report.start_at, report.end_at),
            )
        ]
        # Accepted plans may contain any configured project's human text.
        # Include every configured project in the privacy scope for this context.
        weekly_scope = set(projects) if accepted else present
        call(
            "weekly",
            "weekly",
            list(evidence),
            weekly_scope,
            {
                **context,
                "completed_reviews": completed,
                "pending_reviews": pending,
                "accepted_plans": accepted,
            },
            results,
        )
    report.mechanical = not bool(report.sections)
    return report
