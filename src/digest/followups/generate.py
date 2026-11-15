"""Worker-only, evidence-validated follow-ups with independent source-fidelity checks."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from digest.collectors.base import canonical, content_hash, utc
from digest.config import Config
from digest.followups import records
from digest.llm.contracts import evidence_schema
from digest.llm.grounding import check as check_grounding
from digest.llm.prompts import load, messages
from digest.llm.router import Router
from digest.llm.schemas import Claim, GroundingAudit, Interpretation, Output
from digest.llm.validator import EvidencePackage, validate
from digest.report.model import EvidenceEntry
from digest.util.redact import known_secrets, redact_tree


class FollowupAnswer(Output):
    explanation: list[Claim] = Field(min_length=1, max_length=8)
    interpretation: Interpretation
    limits: list[Claim] = Field(min_length=1, max_length=8)
    missing_information: list[Claim] = Field(max_length=8)
    focus_proposal: Claim | None


def checked(value: dict[str, Any], package: dict[str, Any]) -> FollowupAnswer:
    parsed = FollowupAnswer.model_validate(value)
    evidence = {e["id"]: EvidenceEntry(**e) for e in package["evidence"]}
    validate(parsed, EvidencePackage(evidence, set(package["project_ids"])))
    return parsed


def read_revision(
    db: sqlite3.Connection, config: Config, ident: str, revision: int
) -> dict[str, Any]:
    if type(revision) is not int or not 1 <= revision <= 100000:
        raise ValueError("Invalid follow-up revision")
    request, _ = records.request(db, config, ident)
    original = records.verified(db, "followup_input:" + ident)
    value = records.verified(db, f"followup_revision:{ident}:r{revision}")
    package = value["package"]
    if (
        value.get("id") != ident
        or value.get("revision") != revision
        or value.get("version") != 1
        or value["request_hash"] != content_hash(canonical(request))
        or value["input_hash"] != content_hash(canonical(original))
        or {k: v for k, v in package.items() if k != "project_ids"}
        != {k: v for k, v in original.items() if k != "project_ids"}
        or not set(original["project_ids"]) <= set(package["project_ids"])
        or not {e["project"] for e in package["evidence"]} <= set(package["project_ids"])
    ):
        raise ValueError("Follow-up provenance changed")
    for entry in package["evidence"]:
        if not db.execute("SELECT 1 FROM evidence WHERE id=?", (entry["id"],)).fetchone():
            raise ValueError("Follow-up evidence missing")
    checked(value["answer"], package)
    audit_package = {
        **package,
        "context": {"candidate": value["answer"], "generation_context": package["context"]},
    }
    if not check_grounding(value["audit"], audit_package).approved:
        raise ValueError("Follow-up fidelity unavailable")
    return value


def execute(db: sqlite3.Connection, config: Config, ident: str, router: Router) -> dict[str, Any]:
    ready = records.meta(db, "followup_ready:" + ident)
    if ready is not None:
        return read_revision(db, config, ident, ready)
    request, source = records.request(db, config, ident)
    scope = set(request["privacy_projects"]) | records.privacy(db, config, source)
    if not scope <= {p.id for p in config.projects}:
        raise ValueError("Follow-up privacy policy missing")
    prior = records.meta(db, "followup_state:" + ident)
    attempt = prior["attempts"] + 1
    records.state(db, "followup_state:" + ident, {**prior, "state": "running", "attempts": attempt})
    try:
        package = records.input_package(db, config, ident, now=datetime.now(UTC))
        package = {**package, "project_ids": sorted(scope)}
        package = redact_tree(package, known_secrets(config))
        limit = min(128000, config.limits.max_project_package_chars)
        prompt = load("conceptual", name="followup")
        if len(json.dumps(messages(prompt, package), ensure_ascii=False)) > limit:
            raise ValueError("Follow-up prompt budget exceeded")
        response = router.generate(
            "conceptual",
            project_ids=scope,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            messages=messages(prompt, package),
            schema=evidence_schema(
                FollowupAnswer, {e["id"] for e in package["evidence"]}, max_chars=limit
            ),
            validate=lambda v: checked(v, package),
            section="followup:" + ident,
            package=package,
        )
        if response is None:
            raise ValueError("Follow-up generation unavailable")
        audit_package = {
            **package,
            "context": {
                "candidate": response.value.model_dump(),
                "generation_context": package["context"],
            },
        }
        audit_prompt = load("contrast", name="followup_grounding")
        if len(json.dumps(messages(audit_prompt, audit_package), ensure_ascii=False)) > limit:
            raise ValueError("Follow-up audit budget exceeded")
        audit = router.generate(
            "contrast",
            project_ids=scope,
            prompt_name=audit_prompt.name,
            prompt_version=audit_prompt.version,
            messages=messages(audit_prompt, audit_package),
            schema=evidence_schema(
                GroundingAudit, {e["id"] for e in package["evidence"]}, max_chars=limit
            ),
            validate=lambda v: check_grounding(v, audit_package),
            section="followup-check:" + ident,
            package=audit_package,
        )
        if audit is None or not audit.value.approved:
            raise ValueError("Follow-up source fidelity not established")
        value = {
            "version": 1,
            "id": ident,
            "revision": attempt,
            "created_at": utc(datetime.now(UTC)),
            "request_hash": content_hash(canonical(request)),
            "input_hash": content_hash(canonical(records.verified(db, "followup_input:" + ident))),
            "source_id": request["source_id"],
            "source_revision": request["source_revision"],
            "source_hash": request["source_hash"],
            "package": package,
            "answer": response.value.model_dump(),
            "audit": audit.value.model_dump(),
            "model_info": {
                "answer": {
                    "provider": response.provider,
                    "model": response.model,
                    "cache_key": response.cache_key,
                    "reused": response.reused,
                },
                "audit": {
                    "provider": audit.provider,
                    "model": audit.model,
                    "cache_key": audit.cache_key,
                    "reused": audit.reused,
                },
            },
            "prompt_versions": {"answer": response.prompt_version, "audit": audit.prompt_version},
        }
        db.execute("BEGIN IMMEDIATE")
        try:
            records.immutable(db, f"followup_revision:{ident}:r{attempt}", value)
            records.state(db, "followup_ready:" + ident, attempt)
            records.state(
                db, "followup_state:" + ident, {**prior, "state": "ready", "attempts": attempt}
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return read_revision(db, config, ident, attempt)
    except BaseException:
        records.state(
            db, "followup_state:" + ident, {**prior, "state": "failed", "attempts": attempt}
        )
        raise
