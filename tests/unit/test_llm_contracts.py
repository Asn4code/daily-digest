"""Reference constraints are scoped, immutable and bounded before HTTP."""

import pytest

from digest.llm import schemas
from digest.llm.contracts import evidence_schema


@pytest.mark.parametrize(
    "model",
    [
        schemas.SourceFindings,
        schemas.ProjectDigest,
        schemas.DailyOverview,
        schemas.TomorrowPlan,
        schemas.WeeklyCritical,
        schemas.WeeklyReport,
        schemas.GroundingAudit,
        schemas.Number,
    ],
)
def test_reference_enums_never_mutate_another_package_or_model(model):
    original = model.model_json_schema()
    first = evidence_schema(model, {"ev_b", "ev_a"})
    second = evidence_schema(model, {"ev_other"})
    assert model.model_json_schema() == original
    found = []

    def inspect(value):
        if isinstance(value, dict):
            for key, prop in value.get("properties", {}).items():
                if key in {"evidence", "new_evidence"}:
                    target = prop.get("items", {}) if prop.get("type") == "array" else prop
                    found.append(target["enum"])
                elif key == "confidence":
                    assert prop["enum"] == ["low", "medium", "high"]
                elif key in {"text", "result_id"}:
                    assert "enum" not in prop
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(first)
    assert found and all(refs == ["ev_a", "ev_b"] for refs in found)
    found.clear()
    inspect(second)
    assert found and all(refs == ["ev_other"] for refs in found)


def test_large_reference_schema_is_rejected_before_provider_call():
    with pytest.raises(ValueError, match="schema_budget_exceeded"):
        evidence_schema(schemas.SourceFindings, {f"ev_{n:08}" for n in range(5000)})
    with pytest.raises(ValueError, match="schema_budget_exceeded"):
        evidence_schema(schemas.GroundingAudit, {"ev_one"}, max_chars=100)
