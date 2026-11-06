"""Route validated calls with repair, fallback, privacy and metadata-only audit."""

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from digest.collectors.base import canonical, utc
from digest.config import Config
from digest.llm.client import Client, ClientError, Completion
from digest.llm.diagnostics import error_category, validation_issue
from digest.util.redact import known_secrets, redact_tree

Task = Literal["extract", "conceptual", "plan", "weekly", "contrast"]


@dataclass(frozen=True)
class Routed:
    value: Any
    provider: str
    model: str
    prompt_name: str
    prompt_version: str


class Router:
    def __init__(
        self,
        db: sqlite3.Connection,
        config: Config,
        *,
        job_id: int | None = None,
        client: Client | None = None,
        deadline: float | None = None,
    ) -> None:
        self.db, self.config, self.job_id = db, config, job_id
        self.client = client or Client()
        self.issues: list[dict[str, str]] = []
        self.deadline = (
            deadline
            if deadline is not None
            else (time.monotonic() + config.schedule.max_generation_minutes * 60)
        )

    def generate(
        self,
        task: Task,
        *,
        project_ids: set[str],
        prompt_name: str,
        prompt_version: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        validate: Callable[[dict[str, Any]], Any],
        section: str | None = None,
    ) -> Routed | None:
        projects = {p.id: p for p in self.config.projects}
        if not project_ids or not project_ids <= projects.keys():
            raise ValueError("Unknown or missing project scope")
        external_allowed = all(projects[ident].external_allowed for ident in project_ids)
        for name in getattr(self.config.llm.routing, task):
            if name != "internal" and not external_allowed:
                continue
            provider = self.config.llm.providers[name]
            conversation = list(messages)
            for repair in range(2):
                log_ids: list[int] = []

                def observe(
                    result: Completion | None,
                    error: str | None,
                    latency: int,
                    provider_name: str = name,
                    model: str = provider.model,
                    call_ids: list[int] = log_ids,
                ) -> None:
                    cursor = self.db.execute(
                        "INSERT INTO llm_call(job_id,task,provider,model,prompt_name,"
                        "prompt_version,"
                        "input_tokens,output_tokens,latency_ms,ok,error,created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            self.job_id,
                            task,
                            provider_name,
                            model,
                            prompt_name,
                            prompt_version,
                            result.input_tokens if result else None,
                            result.output_tokens if result else None,
                            latency,
                            int(error is None),
                            canonical(
                                {
                                    "stage": task,
                                    "section": section or task,
                                    "category": error_category(error),
                                    "rule": error,
                                    "field": "$",
                                }
                            )
                            if error
                            else None,
                            utc(datetime.now(UTC)),
                        ),
                    )
                    assert cursor.lastrowid is not None
                    call_ids.append(cursor.lastrowid)

                try:
                    result = self.client.complete(
                        provider,
                        conversation,
                        schema,
                        deadline=self.deadline,
                        observer=observe,
                    )
                    try:
                        value = validate(redact_tree(result.value, known_secrets(self.config)))
                    except ValueError as invalid:
                        detail = {
                            "stage": task,
                            "section": section or task,
                            **validation_issue(invalid, schema),
                        }
                        self.issues.append(detail)
                        if log_ids:
                            self.db.execute(
                                "UPDATE llm_call SET ok=0,error=? WHERE id=?",
                                (canonical(detail), log_ids[-1]),
                            )
                        raise ClientError("output_invalid") from None
                    return Routed(value, name, provider.model, prompt_name, prompt_version)
                except ClientError as error:
                    code = str(error)
                    if code != "output_invalid":
                        detail = {
                            "stage": task,
                            "section": section or task,
                            "category": error_category(code),
                            "rule": code,
                            "field": "$",
                        }
                        self.issues.append(detail)
                        if not log_ids:
                            observe(None, code, 0)
                    if code not in {"invalid_json", "response_invalid", "output_invalid"}:
                        break
                    if repair == 0:
                        # Do not echo untrusted output, exceptions or secret-bearing bodies.
                        conversation += [
                            {
                                "role": "user",
                                "content": (
                                    "Repara solo la salida: devuelve JSON que cumpla el esquema. "
                                    "Usa referencias y cifras de las evidencias originales. "
                                    + "Error de validación: "
                                    + detail["rule"]
                                    + "; campo: "
                                    + detail["field"]
                                ),
                            }
                        ]
        return None
