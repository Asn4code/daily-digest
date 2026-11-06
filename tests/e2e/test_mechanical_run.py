"""Mechanical reports cover all evidence and never execute project contents."""

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from digest.cli import app
from digest.config import Config, load_config
from digest.report.model import Claim
from digest.worker import enqueue, execute
from tests.fixtures.make_projects import build_projects
from tests.fixtures.work import add_current_work
from tests.integration.test_fixtures import _snapshot


@pytest.fixture
def config(tmp_path: Path, valid_llm: None) -> Iterator[Config]:
    path = build_projects(tmp_path / "projects")
    try:
        config = load_config(path)
        add_current_work(config, extra_result=False)
        yield config
    finally:
        (path.parent / "proj-fail/no-access").chmod(0o700)


def test_T01_no_changes_does_not_invent_work(config: Config) -> None:
    now = datetime(2026, 11, 4, 19, tzinfo=UTC)
    first = enqueue(config, "daily", params={"no_send": True})
    execute(config, first, now=now)
    second = enqueue(config, "daily", params={"no_send": True})
    path = Path(execute(config, second, now=now + timedelta(minutes=1)))
    assert "Sin resultados verificables" in path.read_text()
    report = json.loads(path.with_suffix(".json").read_text())
    assert not report["results"]
    assert not report["evidence"]


def test_T11_old_notebook_is_not_a_new_execution(config: Config) -> None:
    now = datetime(2026, 11, 4, 19, tzinfo=UTC)
    job = enqueue(config, "preview", params={"no_send": True})
    path = Path(execute(config, job, now=now))
    report = json.loads(path.with_suffix(".json").read_text())
    assert all(
        e["kind"] not in {"run", "run_error"}
        for e in report["evidence"]
        if "notebook" in e["locator"]
    )
    notebooks = [e for e in report["evidence"] if e["kind"] == "notebook_change"]
    assert notebooks
    assert all(e["time_quality"] == "observed" and e["event_at"] is None for e in notebooks)
    assert all(e["meta"]["stored_outputs_only"] for e in notebooks)
    with sqlite3.connect(Path(config.paths.data_dir) / "digest.db") as db:
        assert db.execute("SELECT closed FROM interval").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM delivery").fetchone() == (0,)


def test_full_capture_preserves_all_project_trees(config: Config) -> None:
    before = {p.id: _snapshot(Path(p.root), include_git=True) for p in config.projects}
    job = enqueue(config, "daily", params={"no_send": True})
    path = Path(execute(config, job, now=datetime(2026, 11, 4, 19, tzinfo=UTC)))
    report = json.loads(path.with_suffix(".json").read_text())
    assert {item["project"] for item in report["results"]} == {p.id for p in config.projects}
    assert any(
        item["project"] == "proj-fail" and item["status"] == "partial"
        for item in report["coverage"]
    )
    assert before == {p.id: _snapshot(Path(p.root), include_git=True) for p in config.projects}
    assert "CET" in path.read_text()


def test_cli_enqueues_then_worker_once_builds_report(config: Config) -> None:
    config_path = Path(config.projects[0].root).parent / "config.yaml"
    runner = CliRunner()
    result = runner.invoke(app, ["--config", str(config_path), "run", "--no-send"])
    assert result.exit_code == 0, result.output
    assert not list(Path(config.paths.data_dir).glob("reports/*/*/report.md"))
    with patch(
        "digest.cli.jobs.execute",
        side_effect=lambda cfg: execute(cfg, now=datetime(2026, 11, 4, 19, tzinfo=UTC)),
    ):
        result = runner.invoke(app, ["--config", str(config_path), "worker", "--once"])
    assert result.exit_code == 0, result.output
    assert list(Path(config.paths.data_dir).glob("reports/*/*/report.md"))


def test_validator_blocks_publication_of_unknown_reference(config: Config) -> None:
    from digest.report.mechanical import build

    def invalid(*args, **kwargs):
        report = build(*args, **kwargs)
        report.open_threads.append(Claim("Unsupported", ["ev_invented"]))
        return report

    job = enqueue(config, "daily", params={"no_send": True})
    with patch("digest.worker.build", side_effect=invalid):
        with pytest.raises(RuntimeError):
            execute(config, job, now=datetime(2026, 11, 4, 19, tzinfo=UTC))
    assert not list(Path(config.paths.data_dir).glob("reports/*/*/report.md"))


def test_report_html_escapes_project_text(config: Config) -> None:
    project = config.projects[0]
    (Path(project.root) / "report.md").write_text(
        '<script>alert("bad")</script>\n![secret](https://example.invalid/collect)'
    )
    job = enqueue(config, "daily", params={"no_send": True})
    path = Path(execute(config, job, now=datetime(2026, 11, 4, 19, tzinfo=UTC)))
    html = path.with_suffix(".html").read_text()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert '<img src="https://example.invalid' not in html
    assert "\\!\\[secret\\]" in path.read_text()
