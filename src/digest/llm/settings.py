"""Versioned model preferences and immutable, secret-free job selections."""

import json
import re
import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from digest.collectors.base import canonical, content_hash, utc
from digest.config import Config, LLMTask, ModelName, StrictModel
from digest.util.redact import known_secrets, redact

TASKS: dict[LLMTask, str] = {
    "extract": "Extracción de evidencias",
    "conceptual": "Síntesis y balances",
    "plan": "Plan diario",
    "weekly": "Informe semanal",
    "contrast": "Contraste y comprobación de fidelidad",
}


class Choice(StrictModel):
    provider: str = Field(min_length=1)
    model: ModelName


class Selection(StrictModel):
    routes: dict[LLMTask, list[Choice]]


def metadata(db: sqlite3.Connection, key: str) -> Any:
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def record(db: sqlite3.Connection, ident: str) -> dict[str, Any]:
    if not re.fullmatch(r"models_[a-f0-9]{32}", ident):
        raise ValueError("Invalid model revision")
    value = metadata(db, "model_revision:" + ident)
    if (
        not isinstance(value, dict)
        or value.get("id") != ident
        or content_hash(canonical(value)) != metadata(db, "model_hash:" + ident)
    ):
        raise ValueError("Model revision changed")
    return value


def overrides(db: sqlite3.Connection) -> tuple[dict[LLMTask, list[Choice]], str | None]:
    ident = metadata(db, "model_current")
    if ident is None:
        return {}, None
    value = record(db, ident)
    return Selection.model_validate({"routes": value["overrides"]}).routes, ident


def expected(db: sqlite3.Connection, config: Config) -> str:
    # Detect YAML edits too, without persisting endpoints or credential variable names.
    return content_hash(canonical([metadata(db, "model_current"), config.llm.model_dump()]))


def validate_choices(config: Config, choices: list[Choice]) -> None:
    names = [c.provider for c in choices]
    if not names or len(names) != len(set(names)) or not set(names) <= config.llm.providers.keys():
        raise ValueError("Unknown or repeated provider")
    hidden = known_secrets(config)
    if any(
        redact(c.provider, hidden) != c.provider or redact(c.model, hidden) != c.model
        for c in choices
    ):
        raise ValueError("Credential-like model selection")


def baseline(config: Config) -> dict[LLMTask, list[Choice]]:
    return {
        task: [
            Choice(
                provider=name,
                model=config.llm.task_models.get(task, {}).get(
                    name, config.llm.providers[name].model
                ),
            )
            for name in getattr(config.llm.routing, task)
        ]
        for task in TASKS
    }


def selection(
    db: sqlite3.Connection, config: Config
) -> tuple[dict[LLMTask, list[Choice]], str | None]:
    custom, ident = overrides(db)
    result = baseline(config) | custom
    for choices in result.values():
        validate_choices(config, choices)
    return result, ident


def save(
    db: sqlite3.Connection,
    config: Config,
    task: LLMTask | None,
    choices: list[Choice] | None,
    etag: str,
    nonce: str,
) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", nonce) or (task is not None and task not in TASKS):
        raise ValueError("Invalid submission")
    if choices is not None:
        if task is None:
            raise ValueError("Missing task")
        validate_choices(config, choices)
    request = {
        "task": task,
        "choices": [c.model_dump() for c in choices] if choices is not None else None,
    }
    prior = metadata(db, "model_submission:" + nonce)
    if prior:
        if prior["request"] != request:
            raise ValueError("Submission already used")
        return str(prior["revision"])
    if etag != expected(db, config):
        raise ValueError("Model settings changed; reload before saving")
    custom, previous = overrides(db)
    if task is None:
        custom = {}
    elif choices is None:
        custom.pop(task, None)
    else:
        custom[task] = choices
    ident = "models_" + secrets.token_hex(16)
    value = {
        "id": ident,
        "created_at": utc(datetime.now(UTC)),
        "previous": previous,
        "task": task,
        "overrides": {t: [c.model_dump() for c in route] for t, route in custom.items()},
    }
    for name, item in (
        ("model_revision:" + ident, value),
        ("model_hash:" + ident, content_hash(canonical(value))),
        ("model_submission:" + nonce, {"request": request, "revision": ident}),
    ):
        db.execute("INSERT INTO meta(key,value) VALUES (?,?)", (name, canonical(item)))
    db.execute(
        "INSERT INTO meta(key,value) VALUES ('model_current',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (canonical(ident),),
    )
    return ident


def provider_hash(config: Config, names: set[str]) -> str:
    return content_hash(
        canonical(
            {
                name: {
                    "base_url": config.llm.providers[name].base_url,
                    "api_key_env": config.llm.providers[name].api_key_env,
                    "timeout_s": config.llm.providers[name].timeout_s,
                }
                for name in sorted(names)
            }
        )
    )


def freeze(db: sqlite3.Connection, config: Config, job: int) -> Config:
    """Caller holds a short writer transaction; retries keep the original selection."""
    key = "model_job:" + str(job)
    frozen = metadata(db, key)
    if frozen is None:
        routes, revision = selection(db, config)
        names = {c.provider for choices in routes.values() for c in choices}
        frozen = {
            "version": 1,
            "revision": revision,
            "routes": {task: [c.model_dump() for c in choices] for task, choices in routes.items()},
            "providers_hash": provider_hash(config, names),
        }
        db.execute("INSERT INTO meta(key,value) VALUES (?,?)", (key, canonical(frozen)))
        db.execute(
            "INSERT INTO meta(key,value) VALUES (?,?)",
            (key + ":hash", canonical(content_hash(canonical(frozen)))),
        )
    if content_hash(canonical(frozen)) != metadata(db, key + ":hash") or frozen.get("version") != 1:
        raise ValueError("Job model selection changed")
    selected = Selection.model_validate({"routes": frozen["routes"]}).routes
    if set(selected) != set(TASKS):
        raise ValueError("Incomplete job model selection")
    for choices in selected.values():
        validate_choices(config, choices)
    names = {c.provider for choices in selected.values() for c in choices}
    if frozen["providers_hash"] != provider_hash(config, names):
        raise ValueError("Job provider configuration changed")
    result = config.model_copy(deep=True)
    for task, choices in selected.items():
        setattr(result.llm.routing, task, [c.provider for c in choices])
        result.llm.task_models[task] = {c.provider: c.model for c in choices}
    return result


def for_task(config: Config, task: LLMTask) -> Config:
    if not config.llm.task_models.get(task):
        return config
    result = config.model_copy(deep=True)
    for name, model in config.llm.task_models.get(task, {}).items():
        result.llm.providers[name].model = model
    return result


def history(db: sqlite3.Connection) -> list[dict[str, Any]]:
    ident = metadata(db, "model_current")
    result = []
    for _ in range(20):
        if ident is None:
            break
        value = record(db, ident)
        result.append(value)
        ident = value["previous"]
    return result
