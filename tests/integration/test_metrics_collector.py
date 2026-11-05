"""Verify numeric summaries and deltas from declared source columns."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from digest.collectors.base import CaptureContext
from digest.collectors.metrics import MetricsCollector
from digest.config import MetricConfig, ProjectConfig, load_config
from tests.fixtures.make_projects import build_projects


def test_fixture_metrics_change_is_calculated(tmp_path: Path) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    project = config.projects[0]
    root = Path(project.root)
    original = (tmp_path / "projects/history/proj-ok/scores-before.csv").read_bytes()
    latest = (root / "results/scores.csv").read_bytes()
    (root / "results/scores.csv").write_bytes(original)
    ctx = CaptureContext(tmp_path / "service", datetime.now(UTC))
    first = MetricsCollector().collect(project, None, ctx)
    assert first.status == "ok"
    assert first.evidence[0].meta["stats"]["rmsd"]["mean"] == 1.5
    ctx.previous_payload = first.snapshot_payload
    assert not MetricsCollector().collect(project, None, ctx).evidence
    (root / "results/scores.csv").write_bytes(latest)
    second = MetricsCollector().collect(project, None, ctx)
    assert second.evidence[0].meta["stats"]["rmsd"] == {
        "n": 2,
        "mean": 1.4,
        "median": 1.4,
        "min": 0.8,
        "max": 2.0,
    }
    assert second.evidence[0].meta["change"]["rmsd"]["mean"] == pytest.approx(-0.1)
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize(
    ("suffix", "content"),
    [
        (".csv", "score\n1\n3\nNaN\nwrong\n"),
        (".tsv", "score\n1\n3\nNaN\nwrong\n"),
        (".json", json.dumps([{"score": 1}, {"score": 3}, {"score": True}, {"score": None}])),
    ],
)
def test_invalid_numbers_are_visible_not_averaged(
    tmp_path: Path, suffix: str, content: str
) -> None:
    name = "scores" + suffix
    (tmp_path / name).write_text(content)
    project = ProjectConfig(
        id="test",
        name="Test",
        root=str(tmp_path),
        metrics=[MetricConfig(label="score", pattern=name, columns=["score"])],
    )
    output = MetricsCollector().collect(
        project, None, CaptureContext(tmp_path / "service", datetime.now(UTC))
    )
    assert output.status == "partial"
    assert output.omitted[0].reason == "invalid_numeric_values"
    assert output.evidence[0].meta["stats"]["score"]["mean"] == 2
    assert output.evidence[0].meta["stats"]["score"]["n"] == 2


def test_missing_declared_column_is_coverage_not_invention(tmp_path: Path) -> None:
    (tmp_path / "scores.csv").write_text("other\n1\n")
    project = ProjectConfig(
        id="test",
        name="Test",
        root=str(tmp_path),
        metrics=[MetricConfig(label="score", pattern="*.csv", columns=["score"])],
    )
    output = MetricsCollector().collect(
        project, None, CaptureContext(tmp_path / "service", datetime.now(UTC))
    )
    assert output.status == "partial" and not output.evidence
    assert output.omitted[0].reason == "missing_column"


def test_large_finite_values_never_publish_infinity(tmp_path: Path) -> None:
    path = tmp_path / "scores.csv"
    path.write_text("score\n1e308\n1e308\n")
    project = ProjectConfig(
        id="test",
        name="Test",
        root=str(tmp_path),
        metrics=[MetricConfig(label="score", pattern="*.csv", columns=["score"])],
    )
    output = MetricsCollector().collect(
        project, None, CaptureContext(tmp_path / "service", datetime.now(UTC))
    )
    assert output.status == "ok"
    assert output.evidence[0].meta["stats"]["score"]["mean"] == 1e308
    assert output.evidence[0].meta["stats"]["score"]["median"] == 1e308
    assert "Infinity" not in output.evidence[0].excerpt
