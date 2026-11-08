"""Safe validation diagnostics without exception text, input values or unknown keys."""

from typing import Any

from pydantic import ValidationError as SchemaError

from digest.llm.validator import ValidationError


def error_category(code: str | None) -> str:
    if code in {"generation_timeout", "provider_timeout"}:
        return "timeout"
    if code in {"invalid_json", "response_invalid"}:
        return "validation"
    return "provider"


def repair_issues(error: ValueError, schema: dict[str, Any] | None) -> list[dict[str, str]]:
    """Expose bounded rule/field diagnostics, never candidate values or error inputs."""
    related = error.related if isinstance(error, ValidationError) else ()
    return [validation_issue(item, schema) for item in (error, *related)[:20]]


def validation_issue(error: ValueError, schema: dict[str, Any] | None) -> dict[str, str]:
    fields: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            fields.update(value.get("properties", {}))
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(schema)
    if isinstance(error, ValidationError):
        rule, path = str(error), error.path
    elif isinstance(error, SchemaError):
        first = error.errors(include_url=False, include_context=False, include_input=False)[0]
        rule, path = "schema_" + first["type"], first["loc"]
    else:
        rule, path = "schema_invalid", ()
    # Only schema-declared field names and numeric list indexes may leave validation.
    field = ".".join(
        str(part) if isinstance(part, int) or part in fields else "<extra>" for part in path
    )
    return {"category": "validation", "rule": rule, "field": field or "$"}
