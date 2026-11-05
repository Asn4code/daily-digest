"""Literal paths, historical intervals and immutable project metadata."""

from datetime import UTC, datetime
from pathlib import Path

from digest.collectors.base import CaptureContext
from digest.collectors.git import GitCollector
from digest.config import load_config
from tests.fixtures.make_projects import _git, build_projects
from tests.integration.test_fixtures import _snapshot


def test_T30_git_capture_preserves_tree_and_index(tmp_path: Path) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    project = config.projects[0]
    root = Path(project.root)
    # Configured project helpers must never run during capture.
    marker = tmp_path / "executed"
    _git(root, "config", "core.fsmonitor", f"touch {marker}")
    _git(root, "config", "diff.external", f"touch {marker}")
    before = _snapshot(root, include_git=True)
    ctx = CaptureContext(tmp_path / "service", datetime(2026, 11, 4, tzinfo=UTC))
    output = GitCollector().collect(project, datetime(2026, 11, 3, tzinfo=UTC), ctx)
    assert output.status == "ok", output.omitted
    commits = [e for e in output.evidence if e.kind == "commit"]
    assert len(commits) == 1
    assert commits[0].event_at.date().isoformat() == "2026-11-03"
    assert any(e.kind == "diff" and e.meta["path"] == "results/scores.csv" for e in output.evidence)
    assert _snapshot(root, include_git=True) == before
    assert not marker.exists()
    ctx.previous_payload = output.snapshot_payload
    assert not GitCollector().collect(project, datetime(2026, 11, 3, tzinfo=UTC), ctx).evidence
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_worktree_binary_and_literal_filenames(tmp_path: Path) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    project = config.projects[2]
    root = Path(project.root)
    name = "space ' $(touch marker)\n.md"
    (root / name).write_text("literal untracked data")
    (root / "new.bin").write_bytes(b"\0binary")
    (root / "private.key").write_text("SECRET_NOT_CAPTURED")
    (root / "results/scores.csv").write_text("model,rmsd\ncontrol,3.0\n")
    _git(root, "add", "results/scores.csv")
    (root / "results/scores.csv").write_text("model,rmsd\ncontrol,4.0\n")
    before = _snapshot(root, include_git=True)
    ctx = CaptureContext(tmp_path / "service", datetime(2026, 11, 4, tzinfo=UTC))
    output = GitCollector().collect(project, None, ctx)
    assert output.status == "partial"
    assert any(item.reason == "outside_root" for item in output.omitted)
    assert any(e.locator == "untracked:" + name for e in output.evidence)
    binary = next(e for e in output.evidence if e.locator == "untracked:new.bin")
    assert binary.meta["binary"] and "binary" not in binary.excerpt
    locators = {e.locator for e in output.evidence}
    assert "staged:results/scores.csv" in locators
    assert "worktree:results/scores.csv" in locators
    assert all("SECRET_NOT_CAPTURED" not in e.excerpt for e in output.evidence)
    assert _snapshot(root, include_git=True) == before
    assert not (root / "marker").exists()
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_external_git_config_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "--initial-branch=main", "--template=")
    _git(root, "config", "include.path", "/etc/private-file")
    from digest.config import ProjectConfig

    project = ProjectConfig(id="test", name="Test", root=str(root))
    output = GitCollector().collect(
        project, None, CaptureContext(tmp_path / "service", datetime.now(UTC))
    )
    assert output.status == "failed"
    assert output.omitted[0].reason == "git_config_include"


def test_T30_clean_filter_cannot_execute_during_worktree_capture(tmp_path: Path) -> None:
    from digest.config import ProjectConfig

    root = tmp_path / "project"
    root.mkdir()
    marker = tmp_path / "filter-executed"
    _git(root, "init", "--initial-branch=main", "--template=")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    (root / "file.md").write_text("initial\n")
    _git(root, "add", "file.md")
    _git(root, "commit", "-m", "initial")
    (root / ".gitattributes").write_text("file.md filter=evil\n")
    _git(root, "config", "filter.evil.clean", f"touch {marker}; cat")
    (root / "file.md").write_text("modified\n")
    before = _snapshot(root, include_git=True)
    result = GitCollector().collect(
        ProjectConfig(id="test", name="Test", root=str(root)),
        None,
        CaptureContext(tmp_path / "service", datetime.now(UTC)),
    )
    assert result.status == "failed"
    assert result.omitted[0].reason == "git_config_filter"
    assert not marker.exists()
    assert _snapshot(root, include_git=True) == before
