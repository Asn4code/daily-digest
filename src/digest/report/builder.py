"""Enrich every mechanical result without losing coverage or human state."""

import json
import sqlite3
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel

from digest.collectors.store import previous_payload
from digest.config import Config
from digest.llm import schemas
from digest.llm.prompts import load, messages
from digest.llm.router import Router, Task
from digest.llm.validator import EvidencePackage, validate
from digest.report.model import EvidenceEntry, Report

SCHEMAS: dict[str, type[BaseModel]] = {
    "extract": schemas.ResultExtraction,
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
        set(payload.get("pending_reviews", [])),
    )


def enrich(db: sqlite3.Connection, config: Config, report: Report, router: Router) -> Report:
    tasks = task_context(db, config)
    projects = {p.id: p for p in config.projects}
    evidence = {e.id: e for e in report.evidence}

    def call(
        task: Task,
        key: str,
        ids: list[str],
        project_ids: set[str],
        context: dict[str, Any],
        result_ids: list[str],
    ) -> None:
        if not ids or not project_ids:
            return
        budget = config.limits.max_project_package_chars
        scoped_tasks = [t for pid in project_ids for t in tasks.get(pid, [])]
        states: dict[str, str] = {}
        for task_item in scoped_tasks:
            ident = task_item["id"]
            states[ident] = "blocked" if ident in states else task_item["state"]
        payload: dict[str, Any] = {
            "project_ids": sorted(project_ids),
            "result_ids": result_ids,
            "task_states": states,
            "context": context,
            "evidence": [],
        }
        prompt = load(task)
        limit = budget * len(project_ids)
        # Large context is omitted explicitly; the mechanical report remains complete.
        if len(json.dumps(messages(prompt, payload), ensure_ascii=False)) > limit:
            report.warnings.append(key + ": contexto supera el límite; sección mecánica.")
            return
        priority = {"task_note": 0, "metric": 1, "task_transition": 2, "run_error": 3, "diff": 4}
        for eid in sorted(set(ids), key=lambda i: priority.get(evidence[i].kind, 5)):
            item = asdict(evidence[eid])
            item["meta"] = {
                k: v
                for k, v in item["meta"].items()
                if k in {"stats", "change", "path", "provenance"}
            }
            payload["evidence"].append(item)
            if len(json.dumps(messages(prompt, payload), ensure_ascii=False)) > limit:
                payload["evidence"].pop()
                report.warnings.append(
                    key + ": evidencia omitida por límite de paquete (" + eid + ")."
                )
        if not payload["evidence"]:
            return
        scope = package_scope(payload)
        schema = SCHEMAS[task]

        def check(value: dict[str, Any]) -> BaseModel:
            parsed = schema.model_validate(value)
            validate(parsed, scope)
            return parsed

        response = router.generate(
            task,
            project_ids=project_ids,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            messages=messages(prompt, payload),
            schema=schema.model_json_schema(),
            validate=check,
        )
        if response is None:
            report.warnings.append(key + ": no hubo respuesta válida; sección mecánica.")
            return
        report.sections[key] = response.value.model_dump()
        report.packages[key] = payload
        report.model_info[key] = {"provider": response.provider, "model": response.model}
        report.prompt_versions[key] = response.prompt_version

    for result in report.results:
        call(
            "extract",
            "extract:" + result.id,
            result.evidence,
            {result.project},
            {"result_id": result.id, "objective": projects[result.project].objective},
            [result.id],
        )
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
    report.mechanical = not bool(report.sections)
    return report
