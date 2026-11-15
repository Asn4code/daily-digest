"""Resolve exact historical phrases and check only bounded, configured metric data."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from digest.collectors.base import content_hash
from digest.config import MetricConfig, ProjectConfig, load_config
from digest.followups.checks import metric_summary
from digest.followups.selection import catalogue, resolve
from digest.report.model import EvidenceEntry, Report

NOW = datetime(2026, 11, 15, 19, tzinfo=UTC)
RAW = b"score,other\n1,7\n2,8\n3,9\n"


@pytest.fixture
def sample(tmp_path):
    config = load_config(Path("config.example.yaml"))
    project = tmp_path / "project"
    project.mkdir()
    (project / "scores.csv").write_bytes(RAW)
    config.projects = [
        ProjectConfig(
            id="demo",
            name="Demo",
            root=str(project),
            metrics=[MetricConfig(label="Score", pattern="*.csv", columns=["score"])],
        )
    ]
    entry = EvidenceEntry(
        "ev_metric",
        "demo",
        "metric",
        "0:scores.csv",
        "Resumen de puntuaciones",
        NOW.isoformat(),
        None,
        "observed",
        {
            "path": "scores.csv",
            "stats": {"score": {"n": 3, "mean": 2.0, "median": 2.0, "min": 1.0, "max": 3.0}},
        },
        content_hash(RAW),
    )
    report = Report(
        "rep_daily_example_r1",
        "daily",
        NOW.isoformat(),
        NOW.isoformat(),
        NOW.isoformat(),
        evidence=[entry],
    )
    report.sections["conceptual"] = {
        "summary": {"text": "La media registrada es 2.", "evidence": [entry.id]}
    }
    yield config, entry, report, project


def test_phrase_identifiers_are_bound_to_revision_and_exact_field_content(sample):
    _, entry, report, _ = sample
    choices = catalogue(report)
    assert len(choices) == 1
    selected, evidence = resolve(report, [choices[0].id])
    assert selected[0].path == ("sections", "conceptual", "summary", "text")
    assert selected[0].text == "La media registrada es 2." and evidence == [entry]
    changed = deepcopy(report)
    changed.id = "rep_daily_example_r2"
    with pytest.raises(ValueError, match="outside original"):
        resolve(changed, [choices[0].id])
    changed.id = report.id
    changed.sections["conceptual"]["summary"]["text"] = "Otro texto"
    with pytest.raises(ValueError, match="outside original"):
        resolve(changed, [choices[0].id])


@pytest.mark.parametrize(
    "ids", [[], ["../../etc/passwd"], ["sections.conceptual.summary.text"], ["sel_missing"]]
)
def test_browser_cannot_supply_paths_or_unknown_selections(sample, ids):
    with pytest.raises(ValueError):
        resolve(sample[2], ids)


def test_selections_have_bounds_and_include_only_cited_evidence(sample):
    _, entry, report, _ = sample
    another = deepcopy(entry)
    another.id = "ev_unrelated"
    report.evidence.append(another)
    ident = catalogue(report)[0].id
    with pytest.raises(ValueError):
        resolve(report, [ident, ident])
    with pytest.raises(ValueError):
        resolve(report, [f"sel_{i}" for i in range(9)])
    _, evidence = resolve(report, [ident])
    assert evidence == [entry]
    report.sections["conceptual"]["uncited"] = {"text": "Sin evidencia", "evidence": ["ev_unknown"]}
    assert len(catalogue(report)) == 1


def test_registered_summary_is_reproduced_without_running_project_code(sample):
    config, entry, _, project = sample
    before = (project / "scores.csv").read_bytes()
    with patch("digest.util.proc.run", side_effect=AssertionError("No project execution")):
        result = metric_summary(config, entry, now=NOW)
    assert result["status"] == "reproduced" and result["mismatches"] == []
    assert result["historical_hash"] == result["current_hash"] == content_hash(RAW)
    assert result["computed"]["score"]["mean"] == 2.0
    assert result["checked_at"] == NOW.isoformat()
    assert result["limits"] and (project / "scores.csv").read_bytes() == before


def test_incorrect_summary_is_discrepancy_only_for_identical_data(sample):
    config, entry, _, project = sample
    entry.meta["stats"]["score"]["mean"] = 5.0
    result = metric_summary(config, entry, now=NOW)
    assert result["status"] == "discrepancy"
    assert result["mismatches"] == [
        {"column": "score", "statistic": "mean", "historical": 5.0, "computed": 2.0}
    ]
    (project / "scores.csv").write_text("score\n4\n5\n6\n")
    result = metric_summary(config, entry, now=NOW)
    assert result["status"] == "changed_data"
    assert result["historical_hash"] == entry.content_hash
    assert result["current_hash"] != entry.content_hash


def test_missing_data_is_not_verifiable_and_never_evidence_of_falsity(sample):
    config, entry, _, project = sample
    (project / "scores.csv").unlink()
    result = metric_summary(config, entry, now=NOW)
    assert result["status"] == "not_verifiable" and result["computed"] == {}


@pytest.mark.parametrize("name", ["../outside.csv", "/tmp/outside.csv", "secret.key", "alias.csv"])
def test_paths_exclusions_and_symlinks_cannot_expand_check_scope(sample, name, tmp_path):
    config, entry, _, project = sample
    outside = tmp_path / "outside.csv"
    outside.write_bytes(RAW)
    (project / "alias.csv").symlink_to(outside)
    entry.meta["path"] = name
    result = metric_summary(config, entry, now=NOW)
    assert result["status"] == "not_verifiable" and result["current_hash"] is None


def test_metric_configuration_and_byte_limits_apply_before_read(sample):
    config, entry, _, _ = sample
    config.limits.max_file_bytes = 1
    assert metric_summary(config, entry, now=NOW)["reason"] == "too_large"
    config.projects[0].metrics[0].columns = ["other"]
    assert metric_summary(config, entry, now=NOW)["reason"] == "metric_configuration_changed"
    entry.kind = "agent_session"
    assert metric_summary(config, entry, now=NOW)["reason"] == "unsupported_source"


def test_nonnumeric_values_and_row_budget_are_explicit(sample):
    config, entry, _, project = sample
    raw = b"score\n1\ninvalid\n3\n"
    (project / "scores.csv").write_bytes(raw)
    entry.content_hash = content_hash(raw)
    entry.meta["stats"]["score"]["n"] = 2
    result = metric_summary(config, entry, now=NOW)
    assert result["status"] == "reproduced" and result["invalid_rows"]["score"] == 1
    assert any("omitidas" in limit for limit in result["limits"])
    (project / "scores.csv").write_text("score\n" + "1\n" * 10001)
    assert metric_summary(config, entry, now=NOW)["reason"] == "row_budget_exceeded"


def test_receipts_redact_known_credentials_in_metadata(sample, monkeypatch):
    config, entry, _, project = sample
    private = "PRIVATE_SYNTHETIC_KEY_123"
    monkeypatch.setenv(config.llm.providers["internal"].api_key_env, private)
    raw = (private + "\n1\n2\n3\n").encode()
    (project / "scores.csv").write_bytes(raw)
    entry.content_hash = content_hash(raw)
    entry.meta["stats"][private] = entry.meta["stats"].pop("score")
    config.projects[0].metrics[0].columns = [private]
    result = metric_summary(config, entry, now=NOW)
    assert result["status"] == "reproduced" and private not in json.dumps(result)


def test_small_magnitude_error_is_not_hidden_by_absolute_tolerance(sample):
    config, entry, _, project = sample
    raw = b"score\n1e-15\n2e-15\n3e-15\n"
    (project / "scores.csv").write_bytes(raw)
    entry.content_hash = content_hash(raw)
    entry.meta["stats"]["score"] = {
        "n": 3,
        "mean": 5e-13,
        "median": 2e-15,
        "min": 1e-15,
        "max": 3e-15,
    }
    receipt = metric_summary(config, entry, now=NOW)
    assert receipt["status"] == "discrepancy"
    assert any(m["statistic"] == "mean" for m in receipt["mismatches"])
    entry.meta["stats"]["score"]["mean"] = receipt["computed"]["score"]["mean"]
    assert metric_summary(config, entry, now=NOW)["status"] == "reproduced"
