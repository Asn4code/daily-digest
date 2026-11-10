"""Worker-only contrast with bounded originals, privacy and source-fidelity audit."""

import json
import sqlite3
from dataclasses import asdict
from typing import Any

from digest.collectors.base import canonical
from digest.config import Config
from digest.llm.contracts import evidence_schema
from digest.llm.grounding import check as check_grounding
from digest.llm.prompts import load, messages
from digest.llm.router import Router
from digest.llm.schemas import Contrast, GroundingAudit
from digest.report.context import human_scope
from digest.review.records import binding, check_contrast, item, read, scope
from digest.util.redact import known_secrets, redact_tree


def execute(db: sqlite3.Connection, config: Config, review_id: str, router: Router) -> str:
    record, report = read(db, config, review_id)
    if record["decision"] or record["mode"] == "minimal" or record["contrast"]:
        return review_id
    project_ids = human_scope(db, config)
    if not project_ids:
        raise ValueError("Human privacy scope unavailable")
    result = item(report, record["result_id"])
    package = {
        "project_ids": sorted(project_ids),
        "result_ids": [result.id],
        "context": {
            "result_id": result.id,
            "title": result.title,
            "human_text": record["human_text"],
            "mode": record["mode"],
            "automatic_summary": report.sections.get("extract:" + result.id),
        },
        "evidence": [asdict(e) for e in report.evidence if e.id in result.evidence],
    }
    package = redact_tree(package, known_secrets(config))
    prompt = load("contrast")
    limit = min(128_000, config.limits.max_project_package_chars)
    if len(json.dumps(messages(prompt, package), ensure_ascii=False)) > limit:
        raise ValueError("Review package exceeds budget")
    evidence = scope(report, result.id)

    def checked(value: dict[str, Any]) -> Contrast:
        parsed = Contrast.model_validate(value)
        check_contrast(parsed, report, record)
        return parsed

    response = router.generate(
        "contrast",
        project_ids=project_ids,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        messages=messages(prompt, package),
        schema=evidence_schema(Contrast, set(evidence.evidence), max_chars=limit),
        validate=checked,
        section="review:" + review_id,
        package=package,
    )
    if response is None:
        raise ValueError("Contrast unavailable")
    audit_package = {
        **package,
        "context": {
            "candidate": response.value.model_dump(),
            "generation_context": package["context"],
        },
    }
    audit_prompt = load("contrast", name="grounding")
    if len(json.dumps(messages(audit_prompt, audit_package), ensure_ascii=False)) > limit:
        raise ValueError("Review audit exceeds budget")
    audit = router.generate(
        "contrast",
        project_ids=project_ids,
        prompt_name=audit_prompt.name,
        prompt_version=audit_prompt.version,
        messages=messages(audit_prompt, audit_package),
        schema=evidence_schema(GroundingAudit, set(evidence.evidence), max_chars=limit),
        validate=lambda value: check_grounding(value, audit_package),
        section="review-check:" + review_id,
        package=audit_package,
    )
    if audit is None or not audit.value.approved:
        raise ValueError("Contrast fidelity not established")
    db.execute("BEGIN IMMEDIATE")
    try:
        changed = db.execute(
            "UPDATE review SET contrast=? WHERE id=? AND decision IS NULL AND contrast IS NULL",
            (canonical(response.value.model_dump()), review_id),
        ).rowcount
        if changed:
            db.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
                (
                    "review_validation:" + review_id,
                    canonical(
                        {
                            "binding": binding(record, response.value, report),
                            "provider": response.provider,
                            "model": response.model,
                            "prompt_version": response.prompt_version,
                            "audit_provider": audit.provider,
                            "audit_model": audit.model,
                            "audit_key": audit.cache_key,
                        }
                    ),
                ),
            )
            db.execute(
                "UPDATE result SET review_state='contrasted' WHERE id=?",
                (result.id,),
            )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return review_id
