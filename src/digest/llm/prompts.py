"""Load versioned service prompts and delimit all project-derived input as data."""

import html
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import yaml

from digest.llm.router import Task


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    task: Task
    body: str


def load(task: Task, *, name: str | None = None) -> Prompt:
    raw = (
        files("digest.llm")
        .joinpath("prompts/" + (name or task) + ".md")
        .read_text(encoding="utf-8")
    )
    _, front, body = raw.split("---", 2)
    meta = yaml.safe_load(front)
    if meta["task"] != task:
        raise ValueError("Invalid prompt metadata")
    return Prompt(meta["name"], str(meta["version"]), task, body.strip())


def messages(prompt: Prompt, package: dict[str, Any]) -> list[dict[str, str]]:
    evidence = package.get("evidence", [])
    context = {key: value for key, value in package.items() if key != "evidence"}
    if prompt.name == "source":
        # Source extraction needs the original evidence and its small context,
        # not the derived-stage validation indexes duplicated around them.
        context = {
            key: context[key] for key in ("project_ids", "result_ids", "context") if key in context
        }
    else:
        # These fields audit dependencies and select the wire projection. They
        # are not scientific context and remain in the stored validation package.
        for key in (
            "parents",
            "auxiliary_evidence",
            "reference_evidence",
            "wire_excerpt_ids",
            "wire_mode",
            "current_evidence_ids",
        ):
            context.pop(key, None)
    blocks = [
        "<context>"
        + html.escape(json.dumps(context, ensure_ascii=False, sort_keys=True))
        + "</context>"
    ]
    for item in evidence:
        if package.get("wire_mode") == "references":
            original = item
            item = {key: original[key] for key in ("id", "project", "kind")}
            if original["id"] in package.get("wire_excerpt_ids", []):
                item.update(
                    event_at=original["event_at"],
                    observed_at=original["observed_at"],
                    time_quality=original["time_quality"],
                    capture_origin=original["meta"].get("capture_origin"),
                    # A partial sentence can reverse a decision. Send a bounded
                    # complete excerpt or rely on the validated source fiche.
                    excerpt=original["excerpt"] if len(original["excerpt"]) <= 1000 else None,
                    excerpt_included=len(original["excerpt"]) <= 1000,
                )
        blocks.append(
            '<evidence id="'
            + html.escape(item["id"], quote=True)
            + '">'
            + html.escape(json.dumps(item, ensure_ascii=False, sort_keys=True))
            + "</evidence>"
        )
    return [
        {"role": "system", "content": prompt.body},
        {"role": "user", "content": "\n".join(blocks)},
    ]
