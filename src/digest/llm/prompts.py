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
    blocks = ["<context>" + html.escape(json.dumps(context, ensure_ascii=False)) + "</context>"]
    for item in evidence:
        blocks.append(
            '<evidence id="'
            + html.escape(item["id"], quote=True)
            + '">'
            + html.escape(json.dumps(item, ensure_ascii=False))
            + "</evidence>"
        )
    return [
        {"role": "system", "content": prompt.body},
        {"role": "user", "content": "\n".join(blocks)},
    ]
