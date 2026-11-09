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
from digest.llm.contracts import evidence_schema
from digest.llm.grounding import check as check_grounding
from digest.llm.prompts import Prompt, load, messages
from digest.llm.router import Router, Task
from digest.llm.validator import EvidencePackage, validate
from digest.report.activity import active_results, classify, current_evidence_ids
from digest.report.assembly import VERSION as ASSEMBLY_VERSION
from digest.report.assembly import assemble
from digest.report.context import human_context
from digest.report.daily import build as build_daily
from digest.report.model import EvidenceEntry, Report, ResultEntry
from digest.report.observations import normalize
from digest.report.packets import SOURCE_PACKET_CHARS, Packet
from digest.report.packets import plan as plan_packets
from digest.report.weekly import build as build_weekly
from digest.util.redact import known_secrets, redact, redact_tree

SCHEMAS: dict[str, type[BaseModel]] = {
    "extract": schemas.ResultFiche,
    "source": schemas.SourceFindings,
    "project": schemas.ProjectDigest,
    "conceptual": schemas.DailyOverview,
    "plan": schemas.TomorrowPlan,
    "weekly": schemas.WeeklyReport,
    "critical": schemas.WeeklyCritical,
    "check": schemas.GroundingAudit,
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
        dict(payload.get("result_projects", {})),
        set(payload.get("closed_results", [])),
        set(payload.get("human_plan_ids", [])),
        payload.get("active_plan_id"),
        dict(payload.get("project_task_states", {})),
        {rid: set(ids) for rid, ids in payload.get("result_evidence", {}).items()},
        dict(payload.get("conclusions", {})),
        dict(payload.get("critical", {})),
        set(payload.get("context", {}).get("project_balances", {})),
        {
            pid: {
                field: value[field]
                for field in (
                    "project_id",
                    "progress_vs_objective",
                    "decisions",
                    "hypotheses_changed",
                )
            }
            for pid, value in payload.get("context", {}).get("project_balances", {}).items()
        },
        bool(
            payload.get("human_plan_ids")
            or payload.get("context", {}).get("human_doubts")
            or payload.get("context", {}).get("accepted_plans")
            or payload.get("context", {}).get("current_human_plan", {}).get("accepted_plan")
            or any(p["author"] == "human" for p in payload.get("conclusions", {}).values())
        ),
    )


def enrich(db: sqlite3.Connection, config: Config, report: Report, router: Router) -> Report:
    classify(report)
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
    report.project_context = {
        p.id: {"name": redact(p.name, secrets), "objective": redact(p.objective, secrets)}
        for p in config.projects
        if any(r.project == p.id for r in report.results)
    }
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
    report.human_context = human_context(db, config, tasks)
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
        evidence.update({e.id: e for e in report.evidence})
        if any(evidence[eid].project not in project_ids for eid in ids):
            raise ValueError("Evidence outside project scope")
        states: dict[str, str] = {}
        if "_task_states" not in context:
            scoped_tasks = [t for pid in project_ids for t in tasks.get(pid, [])]
            for task_item in scoped_tasks:
                ident = task_item["id"]
                states[ident] = "blocked" if ident in states else task_item["state"]
        payload: dict[str, Any] = {
            "project_ids": sorted(project_ids),
            "result_ids": result_ids,
            "task_states": context.get("_task_states", states),
            "project_task_states": context.get("_project_task_states", {}),
            "conclusions": context.get("_conclusions", {}),
            "critical": context.get("_critical", {}),
            "human_plan_ids": context.get("_human_plan_ids", []),
            "active_plan_id": context.get("_active_plan_id"),
            "result_projects": {r.id: r.project for r in report.results if r.id in result_ids},
            "result_evidence": {
                r.id: sorted(set(r.evidence) & set(ids))
                for r in report.results
                if r.id in result_ids
            },
            "closed_results": [],
            "parents": context.get("_parents", []),
            "auxiliary_evidence": context.get("_auxiliary", []),
            "reference_evidence": context.get("_reference_evidence", []),
            "wire_excerpt_ids": context.get("_wire_excerpt_ids", []),
            "context": {
                **{k: v for k, v in context.items() if not k.startswith("_")},
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
                    "by",
                    "agent",
                    "role",
                    "author",
                    "state",
                    "execution_count",
                    "cell_type",
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
        contract: str | None = None,
        prompt_name: str | None = None,
        wire_mode: str = "full",
        char_limit: int | None = None,
        cutoff: float | None = None,
    ) -> None:
        if not ids or not project_ids:
            mark_pending(key, "input", "no_evidence")
            return
        prompt = load(task, name="source" if source else prompt_name)
        limit = config.limits.max_project_package_chars * len(project_ids)
        if source:
            limit = min(limit, SOURCE_PACKET_CHARS)
        if char_limit is not None:
            limit = min(limit, char_limit)
        payload = payload_for(ids, project_ids, context, result_ids)
        payload["wire_mode"] = wire_mode
        if wire_mode == "references":
            current = current_evidence_ids(report) & set(ids)
            payload["current_evidence_ids"] = sorted(current)
            payload["result_evidence"] = {
                rid: sorted(set(refs) & current) for rid, refs in payload["result_evidence"].items()
            }
        if task == "conceptual" and contract is None:
            payload["closed_results"] = [
                r.id
                for r in report.results
                if r.review_state == "closed_by_human" and r.id in result_ids
            ]
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
        elif wire_mode == "references":
            if len(json.dumps(messages(prompt, payload), ensure_ascii=False)) > limit:
                mark_pending(key, "input", "derived_package_budget_exceeded")
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
        schema = schemas.SourceFindings if source else SCHEMAS[contract or task]
        try:
            schema_limit = config.limits.max_project_package_chars * len(project_ids)
            output_schema = evidence_schema(schema, set(scope.evidence), max_chars=schema_limit)
            audit_schema = evidence_schema(
                schemas.GroundingAudit, set(scope.evidence), max_chars=schema_limit
            )
        except ValueError:
            mark_pending(key, "input", "schema_budget_exceeded")
            return

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
        deadline = (
            cutoff
            if cutoff is not None
            else (
                min(source_deadline, time.monotonic() + allowance)
                if source
                else synthesis_deadline
                if task == "conceptual"
                else router.deadline
            )
        )
        grounding_prompt = load("contrast", name="grounding")
        layer_name = (
            "grounding_overview"
            if schema is schemas.DailyOverview
            else "grounding_critical"
            if schema is schemas.WeeklyCritical
            else None
        )
        if layer_name is not None:
            layer = load("contrast", name=layer_name)
            grounding_prompt = Prompt(
                layer.name,
                grounding_prompt.version + "." + layer.version,
                "contrast",
                grounding_prompt.body + "\n\n" + layer.body,
            )
        for attempt in range(2):
            response = router.generate(
                task,
                project_ids=project_ids,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                messages=messages(prompt, payload),
                schema=output_schema,
                validate=check,
                section=key,
                package=payload,
                deadline=deadline,
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
            order = sorted(config.llm.routing.contrast, key=lambda name: name == response.provider)
            audit_package = {
                **payload,
                "parents": [key],
                "context": {
                    "target_section": key,
                    "candidate": response.value.model_dump(),
                    "generation_context": {
                        k: v for k, v in payload["context"].items() if k != "validation_feedback"
                    },
                    "provider_order": order,
                },
            }
            # The checker sees complete originals, including controls omitted from
            # the compact synthesis projection. It never chooses additional files.
            audit_messages = messages(grounding_prompt, {**audit_package, "wire_mode": "full"})
            if len(json.dumps(audit_messages, ensure_ascii=False)) > min(
                128_000, config.limits.max_project_package_chars * len(project_ids)
            ):
                mark_pending(key, "input", "grounding_package_budget_exceeded")
                return

            def audit_check(
                value: dict[str, Any], package: dict[str, Any] = audit_package
            ) -> schemas.GroundingAudit:
                return check_grounding(value, package)

            audited = router.generate(
                "contrast",
                project_ids=project_ids,
                prompt_name=grounding_prompt.name,
                prompt_version=grounding_prompt.version,
                messages=audit_messages,
                schema=audit_schema,
                validate=audit_check,
                section="check:" + key,
                package=audit_package,
                deadline=deadline,
            )
            if audited is None:
                mark_pending(key, "grounding", "grounding_unavailable")
                return
            if audited.value.approved:
                check_key = "check:" + key
                report.sections[check_key] = audited.value.model_dump()
                report.packages[check_key] = audit_package
                report.model_info[check_key] = {
                    "provider": audited.provider,
                    "model": audited.model,
                    "cache_key": audited.cache_key,
                    "reused": str(audited.reused).lower(),
                }
                report.prompt_versions[check_key] = audited.prompt_version
                break
            if attempt:
                mark_pending(key, "grounding", "grounding_rejected")
                return
            payload["context"]["validation_feedback"] = audited.value.model_dump()
            if len(json.dumps(messages(prompt, payload), ensure_ascii=False)) > limit:
                mark_pending(key, "input", "repair_package_budget_exceeded")
                return
        assert response is not None
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
    active = active_results(report)
    for result in active:
        context: dict[str, Any] = {
            "result_id": result.id,
            "title": result.title,
            "task_id": result.task_id,
            "objective": projects[result.project].objective,
            "external_allowed": projects[result.project].external_allowed,
            "_task_states": {result.task_id: "context"} if result.task_id else {},
        }

        def size(
            ids: list[str], result: ResultEntry = result, context: dict[str, Any] = context
        ) -> int:
            payload = payload_for(ids, {result.project}, context, [result.id])
            payload["wire_mode"] = "full"
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
        payload["task_states"] = {
            ident: state
            for child in keys
            for ident, state in report.packages[child]["task_states"].items()
        }
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
    if any("extract:" + item.id not in report.sections for item in active):
        for key in ["weekly"] if report.kind == "weekly" else ["conceptual", "plan"]:
            mark_pending(key, "dependency", "extraction_pending")
        report.mechanical = not bool(report.sections)
        return report
    if not active:
        report.mechanical = False
        return report
    if report.kind != "weekly":
        build_daily(
            db,
            config,
            report,
            call,
            tasks,
            project_deadline=started + duration * 0.8,
            overview_deadline=started + duration * 0.9,
            deadline=router.deadline,
        )
    else:
        build_weekly(
            db,
            config,
            report,
            call,
            tasks,
            critical_deadline=started + duration * 0.85,
            deadline=router.deadline,
        )
    report.mechanical = not bool(report.sections)
    return report
