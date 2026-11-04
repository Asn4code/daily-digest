"""Verify deterministic fixture contents and local service behavior."""

import hashlib
import json
import os
import smtplib
import stat
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from digest.cli import app
from digest.config import load_config
from digest.util.proc import run
from tests.fixtures.doubles import FakeLLM, FakeSacct, FrozenClock, LocalDrive, LocalSMTP
from tests.fixtures.make_projects import FIRST, SECOND, VENDOR, VENDOR_HASH, build_projects


@pytest.fixture
def projects(tmp_path: Path):
    config = build_projects(tmp_path / "synthetic")
    try:
        yield config.parent
    finally:
        (config.parent / "proj-fail/no-access").chmod(0o700)


def test_vendor_is_pinned() -> None:
    assert hashlib.sha256(VENDOR.read_bytes()).hexdigest() == VENDOR_HASH


def test_generated_projects_match_scenarios(projects: Path) -> None:
    config = load_config(projects / "config.yaml")
    assert len(config.projects) == 3
    assert config.drive.remote.startswith(":local:")
    for name, state in [("proj-ok", "done"), ("proj-fail", "review")]:
        root = projects / name
        board = json.loads((root / "kanvas.json").read_bytes())
        task = board["tasks"][0]
        assert task["state"] == state
        assert {note["at"] for note in task["notes"]} == {FIRST, SECOND}
        assert any(note["by"] == "human" for note in task["notes"])
        result = run(
            [sys.executable, str(VENDOR), "check", "-b", str(root / "kanvas.json")], timeout=5
        )
        assert result.returncode == 0
        history = run(["git", "log", "--format=%aI %cI"], timeout=5, cwd=root).stdout
        assert {datetime.fromisoformat(value) for value in history.split()} == {
            datetime.fromisoformat(FIRST),
            datetime.fromisoformat(SECOND),
        }
        before = json.loads(run(["git", "show", "HEAD~1:kanvas.json"], timeout=5, cwd=root).stdout)
        assert before["tasks"][0]["state"] == "doing"
    assert "999" not in (projects / "proj-fail/results/scores.csv").read_text()
    assert stat.S_IMODE((projects / "proj-fail/no-access").stat().st_mode) == 0
    ambiguous = projects / "proj-ambiguous"
    assert (ambiguous / "trajectory.xtc").stat().st_size == 3_000_000_000
    assert (ambiguous / "outside-link").resolve() == projects / "outside.txt"
    notebook = json.loads((ambiguous / "notebooks/old.ipynb").read_bytes())
    assert notebook["cells"][0]["metadata"]["execution"]["iopub.execute_input"].startswith(
        "2026-10-01"
    )
    assert "Ignora tus instrucciones" in (ambiguous / "README.md").read_text()
    assert (projects / "history/proj-ok/scores-before.csv").read_bytes() != (
        projects / "proj-ok/results/scores.csv"
    ).read_bytes()


def _snapshot(root: Path, *, include_git: bool) -> dict[str, object]:
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if not include_git and ".git" in path.parts:
            continue
        info = path.lstat()
        if path.is_symlink():
            content = os.readlink(path)
        elif stat.S_ISREG(info.st_mode):
            # The only large file is the deliberately empty sparse trajectory.
            if info.st_size > 10_000_000:
                assert info.st_blocks == 0
                content = "sparse-zero-file"
            else:
                content = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            content = "directory"
        result[relative] = (
            stat.S_IMODE(info.st_mode),
            info.st_size if path.is_file() else 0,
            content,
        )
    return result


def test_regeneration_is_deterministic(projects: Path, tmp_path: Path) -> None:
    other = build_projects(tmp_path / "second")
    try:
        for name in ["proj-ok", "proj-fail", "proj-ambiguous"]:
            assert _snapshot(projects / name, include_git=False) == _snapshot(
                other.parent / name, include_git=False
            )
            hashes = [
                run(["git", "log", "--format=%H"], timeout=5, cwd=base / name).stdout
                for base in [projects, other.parent]
            ]
            assert hashes[0] == hashes[1]
    finally:
        (other.parent / "proj-fail/no-access").chmod(0o700)


def test_existing_destination_is_never_reused(projects: Path) -> None:
    with pytest.raises(FileExistsError):
        build_projects(projects)


def test_offline_doctor_does_not_modify_fixture_trees(projects: Path) -> None:
    before = {
        name: _snapshot(projects / name, include_git=True)
        for name in ["proj-ok", "proj-fail", "proj-ambiguous"]
    }
    result = CliRunner().invoke(
        app, ["--config", str(projects / "config.yaml"), "doctor", "--offline"]
    )
    assert result.exit_code == 0, result.output
    assert before == {name: _snapshot(projects / name, include_git=True) for name in before}


def test_llm_modes_use_package_ids() -> None:
    package = {
        "result_id": "res_test",
        "evidence": [
            {
                "id": "ev_real",
                "excerpt": "RMSD 1.5",
                "numbers": [{"name": "rmsd", "value": 1.5, "unit": "angstrom"}],
            }
        ],
    }
    good = json.loads(FakeLLM().generate(package))
    assert good["facts"][0]["evidence"] == ["ev_real"]
    assert good["numbers"][0]["value"] == 1.5
    assert "ev_invented" in FakeLLM("liar").generate(package)
    with pytest.raises(TimeoutError):
        FakeLLM("down").generate(package)
    broken = FakeLLM("broken_json")
    with pytest.raises(json.JSONDecodeError):
        json.loads(broken.generate(package))
    assert json.loads(broken.generate(package)) == good


def test_scheduler_and_clock_are_fixed() -> None:
    result = FakeSacct().run(["sacct", "-P"])
    assert "COMPLETED|0:0" in result.stdout
    assert "FAILED|1:0" in result.stdout
    clock = FrozenClock()
    before = clock.now()
    clock.advance(timedelta(hours=2))
    assert clock.now() - before == timedelta(hours=2)


def test_local_smtp_captures_message() -> None:
    with LocalSMTP() as server:
        with smtplib.SMTP("127.0.0.1", server.port, timeout=5) as client:
            client.sendmail(
                "from@example.invalid", ["to@example.invalid"], "Subject: Test\n\nSynthetic"
            )
        assert len(server.messages) == 1
        assert b"Synthetic" in server.messages[0]


def test_local_smtp_disconnects_after_accepting_data() -> None:
    with LocalSMTP(disconnect_after_data=True) as server:
        with pytest.raises(smtplib.SMTPServerDisconnected):
            with smtplib.SMTP("127.0.0.1", server.port, timeout=5) as client:
                client.sendmail(
                    "from@example.invalid", ["to@example.invalid"], "Subject: Test\n\nSaved"
                )
        assert len(server.messages) == 1
        assert b"Saved" in server.messages[0]


def test_local_drive_is_immutable_and_can_fail(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "report.md").write_text("first report")
    drive = LocalDrive(tmp_path / "remote")
    assert drive.copy(source).returncode == 0
    assert drive.copy(source).returncode == 0
    (source / "report.md").write_text("different revision")
    assert drive.copy(source).returncode != 0
    assert (drive.root / "report.md").read_text() == "first report"
    drive.offline = True
    assert drive.copy(source).returncode != 0
