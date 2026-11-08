"""Constrain reference decoding to the exact, bounded evidence scope."""

import json
from copy import deepcopy
from typing import Any

from pydantic import BaseModel

MAX_SCHEMA_CHARS = 32_000


def evidence_schema(
    model: type[BaseModel], evidence_ids: set[str], *, max_chars: int = MAX_SCHEMA_CHARS
) -> dict[str, Any]:
    schema = deepcopy(model.model_json_schema())
    references = sorted(evidence_ids)

    def constrain(value: Any) -> None:
        if isinstance(value, dict):
            for name, prop in value.get("properties", {}).items():
                if name in {"evidence", "new_evidence"}:
                    target = prop.get("items", {}) if prop.get("type") == "array" else prop
                    if target.get("type") == "string":
                        target["enum"] = list(references)
            for child in value.values():
                constrain(child)
        elif isinstance(value, list):
            for child in value:
                constrain(child)

    constrain(schema)
    if len(json.dumps(schema, ensure_ascii=False)) > min(MAX_SCHEMA_CHARS, max_chars):
        raise ValueError("schema_budget_exceeded")
    return schema
