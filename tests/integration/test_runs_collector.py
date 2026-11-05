"""Local execution logs and Slurm doubles remain independent."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from digest.collectors.base import CaptureContext
from digest.collectors.runs import RunsCollector
from digest.config import ProjectConfig, RunsConfig, SlurmConfig
from digest.util.proc import ProcessError, ProcessResult
from tests.fixtures.doubles import FakeSacct


def test_log_errors_and_repeat_capture(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "run.log").write_text("2026-11-03T18:00:00Z ERROR synthetic failure\n")
    project = ProjectConfig(id="p", name="P", root=str(root), runs=RunsConfig(logs=["*.log"]))
    ctx = CaptureContext(tmp_path / "service", datetime(2026, 11, 4, tzinfo=UTC))
    output = RunsCollector().collect(project, None, ctx)
    assert output.status == "ok"
    assert output.evidence[0].kind == "run_error"
    assert output.evidence[0].event_at is not None
    ctx.previous_payload = output.snapshot_payload
    assert not RunsCollector().collect(project, None, ctx).evidence


def test_sacct_failure_keeps_other_log_evidence(tmp_path: Path) -> None:
    (tmp_path / "run.log").write_text("WARNING observed log without timestamp\n")
    project = ProjectConfig(
        id="p",
        name="P",
        root=str(tmp_path),
        runs=RunsConfig(logs=["*.log"], slurm=SlurmConfig(enabled=True, user="fixture")),
    )
    ctx = CaptureContext(tmp_path / "service", datetime.now(UTC))
    with patch("digest.collectors.runs.run", side_effect=ProcessError("unavailable")):
        output = RunsCollector().collect(project, None, ctx)
    assert output.status == "partial" and output.evidence
    assert output.evidence[0].event_at is None
    assert output.omitted[0].reason == "sacct_unavailable"


def test_fake_sacct_respects_project_and_missing_timezone(tmp_path: Path) -> None:
    project = ProjectConfig(
        id="p",
        name="P",
        root=str(tmp_path),
        runs=RunsConfig(slurm=SlurmConfig(enabled=True, user="fixture")),
    )
    ctx = CaptureContext(tmp_path / "service", datetime.now(UTC))
    fake = FakeSacct().run(["sacct"])
    response = ProcessResult(
        0,
        fake.stdout.replace("/synthetic/proj-ok", str(tmp_path)).replace(
            "/synthetic/proj-fail", str(tmp_path)
        ),
        fake.stderr,
    )
    with patch("digest.collectors.runs.run", return_value=response):
        output = RunsCollector().collect(project, None, ctx)
    assert {e.kind for e in output.evidence} == {"run", "run_error"}
    assert all(e.event_at is None for e in output.evidence)
    ctx.previous_payload = output.snapshot_payload
    with patch("digest.collectors.runs.run", return_value=response):
        assert not RunsCollector().collect(project, None, ctx).evidence
