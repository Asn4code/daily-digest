"""Route validated calls with repair, fallback, privacy and metadata-only audit."""

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from digest.collectors.base import canonical, content_hash, utc
from digest.config import Config
from digest.llm.cache import Nodes
from digest.llm.client import Client, ClientError, Completion
from digest.llm.diagnostics import error_category, repair_issues, validation_issue
from digest.util.redact import known_secrets, redact_tree

Task = Literal["extract", "conceptual", "plan", "weekly", "contrast"]


@dataclass(frozen=True)
class Routed:
    value: Any
    provider: str
    model: str
    prompt_name: str
    prompt_version: str
    cache_key: str = ""
    reused: bool = False


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
        deadline: float | None = None,
        package: dict[str, Any] | None = None,
    ) -> Routed | None:
        projects = {p.id: p for p in self.config.projects}
        if not project_ids or not project_ids <= projects.keys():
            raise ValueError("Unknown or missing project scope")
        external_allowed = all(projects[ident].external_allowed for ident in project_ids)
        eligible = [
            name
            for name in getattr(self.config.llm.routing, task)
            if name == "internal" or external_allowed
        ]
        nodes = Nodes(self.config)
        clean_package = redact_tree(package, known_secrets(self.config))
        cache_key = nodes.key(
            task, project_ids, messages, schema, prompt_name, prompt_version, clean_package
        )

        def remember() -> None:
            if self.job_id is not None:
                row = self.db.execute(
                    "SELECT params FROM job WHERE id=?", (self.job_id,)
                ).fetchone()
                if row:
                    params = json.loads(row[0])
                    params.setdefault("nodes", {})[section or task] = cache_key
                    self.db.execute(
                        "UPDATE job SET params=? WHERE id=?", (canonical(params), self.job_id)
                    )

        def check_cached(value: dict[str, Any]) -> Any:
            return validate(redact_tree(value, known_secrets(self.config)))

        cached = nodes.load(
            cache_key,
            check_cached,
            content_hash(canonical(clean_package)) if clean_package is not None else None,
        )
        if cached and cached.provider in eligible:
            remember()
            return Routed(
                cached.value,
                cached.provider,
                cached.model,
                prompt_name,
                prompt_version,
                cache_key,
                True,
            )
        call_deadline = min(self.deadline, deadline) if deadline is not None else self.deadline
        for index, name in enumerate(eligible):
            provider = self.config.llm.providers[name]
            remaining = max(0.0, call_deadline - time.monotonic())
            provider_deadline = min(
                call_deadline, time.monotonic() + remaining / (len(eligible) - index)
            )
            conversation = list(messages)
            for repair in range(2):
                log_ids: list[int] = []
                rejected_fields: list[dict[str, str]] = []

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
                        deadline=provider_deadline,
                        observer=observe,
                    )
                    try:
                        sanitized = redact_tree(result.value, known_secrets(self.config))
                        value = validate(sanitized)
                    except ValueError as invalid:
                        rejected_fields = repair_issues(invalid, schema)
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
                    # Persist sanitized, validated output before starting another node.
                    nodes.save(
                        cache_key,
                        sanitized,
                        name,
                        provider.model,
                        clean_package,
                    )
                    remember()
                    return Routed(
                        value, name, provider.model, prompt_name, prompt_version, cache_key
                    )
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
                                    "Revisa la salida completa sin introducir otros errores: "
                                    "sin HTML ni marcadores de nombre entre ángulos; "
                                    "describe su función sin inventar un archivo. "
                                    + "Error de validación: "
                                    + detail["rule"]
                                    + "; campo: "
                                    + detail["field"]
                                    + (
                                        ". En el cotejo, source_quote es una cita breve y "
                                        "contigua de una única fuente: no unas fragmentos "
                                        "ni normalices espacios o saltos de línea. field "
                                        "debe ser una ruta existente de candidate. "
                                        "Los índices de listas son enteros JSON. No antepongas "
                                        "checks a un campo situado en la raíz de candidate. "
                                        "approved=true exige issues vacía."
                                        if schema and schema.get("title") == "GroundingAudit"
                                        else ""
                                    )
                                    + (
                                        ". Revisa todos estos campos en la misma reparación: "
                                        + canonical(rejected_fields)
                                        if len(rejected_fields) > 1
                                        else ""
                                    )
                                    + (
                                        ". Cada cifra se comprueba solo contra los IDs citados "
                                        "en ese campo. Si procede de otra evidencia del paquete, "
                                        "cita su ID exacto; no cambies el valor. Conserva unidades "
                                        "y etiquetas literales. Puedes separar la prosa con "
                                        "puntuación, después de la unidad si existe. No ocultes "
                                        "unidades ni escribas cifras con palabras para eludir "
                                        "la comprobación."
                                        if detail["rule"] == "unsupported_number"
                                        or any(
                                            i["rule"] == "unsupported_number"
                                            for i in rejected_fields
                                        )
                                        else ""
                                    )
                                    + (
                                        ". No uses etiquetas HTML ni marcadores de nombre "
                                        "entre ángulos. Si la fuente contiene un nombre "
                                        "provisional con ese marcador, describe su función "
                                        "sin reproducirlo; no inventes otro archivo."
                                        if detail["rule"] == "html_forbidden"
                                        or any(
                                            i["rule"] == "html_forbidden" for i in rejected_fields
                                        )
                                        else ""
                                    )
                                ),
                            }
                        ]
        return None
