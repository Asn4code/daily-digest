"""Capture trusted synthetic boards without changing their trees."""

import json
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from digest.collectors.base import CaptureContext
from digest.collectors.kanvas import KanvasCollector
from digest.collectors.store import persist, previous_payload
from digest.config import ProjectConfig, load_config
from digest.db import connect
from digest.util.proc import ProcessResult
from tests.fixtures.make_projects import VENDOR, build_projects
from tests.integration.test_fixtures import _snapshot


def context(tmp_path: Path) -> CaptureContext:
    return CaptureContext(
        tmp_path / "data",
        datetime(2026, 11, 4, tzinfo=UTC),
        kanvas_command=(sys.executable, str(VENDOR)),
    )


def test_capture_transitions_notes_and_database_deduplication(tmp_path: Path) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    project = config.projects[0]
    collector = KanvasCollector()
    ctx = context(tmp_path)
    before = _snapshot(Path(project.root), include_git=True)
    with closing(connect(tmp_path / "digest.db")) as db:
        # The historical fixture snapshot records the state before finish.
        ctx.previous_payload = {
            "tasks": {
                t["id"]: t
                for t in json.loads(
                    (tmp_path / "projects/history/proj-ok/kanvas-before.json").read_text()
                )["tasks"]
            }
        }
        output = collector.collect(project, None, ctx)
        assert output.status == "ok"
        transition = next(e for e in output.evidence if e.kind == "task_transition")
        assert transition.meta["previous_state"] == "doing"
        assert transition.meta["state"] == "done"
        assert transition.event_at is None
        notes = [e for e in output.evidence if e.kind == "task_note"]
        assert notes and all(e.event_at is not None for e in notes)
        assert {e.meta["by"] for e in notes} == {"fixture-agent", "human"}
        first = persist(db, project, "kanvas", output, ctx)
        persist(db, project, "kanvas", output, ctx)
        assert db.execute("SELECT count(*) FROM evidence").fetchone()[0] == len(first)
        assert db.execute('SELECT count(*) FROM evidence WHERE time_quality="event"').fetchone()[
            0
        ] == len(notes)
        ctx.previous_payload = previous_payload(db, project.id, "kanvas")
        repeat = collector.collect(project, None, ctx)
        assert repeat.status == "ok" and not repeat.evidence
    assert _snapshot(Path(project.root), include_git=True) == before
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_T05_missing_project_or_failed_check(tmp_path: Path) -> None:
    project = ProjectConfig(id="test", name="Test", root=str(tmp_path / "missing"))
    collector = KanvasCollector()
    ctx = context(tmp_path)
    assert collector.collect(project, None, ctx).status == "failed"
    root = tmp_path / "project"
    root.mkdir()
    project.root = str(root)
    (root / "kanvas.json").write_text('{"kanvas":1,"groups":[],"tasks":[]}')
    before = (root / "kanvas.json").read_bytes()
    with patch("digest.collectors.kanvas.run", return_value=ProcessResult(1, "SECRET", "SECRET")):
        result = collector.collect(project, None, ctx)
    assert result.status == "failed" and not result.evidence
    assert result.omitted[0].reason == "kanvas_check_failed"
    assert "SECRET" not in repr(result)
    assert (root / "kanvas.json").read_bytes() == before


def test_T06_unknown_board_schema_is_not_executed(tmp_path: Path) -> None:
    project = ProjectConfig(id="test", name="Test", root=str(tmp_path))
    (tmp_path / "kanvas.json").write_text('{"kanvas":2,"tasks":[]}')
    with patch("digest.collectors.kanvas.run", side_effect=AssertionError("must not run")):
        output = KanvasCollector().collect(project, None, context(tmp_path / "service"))
    assert output.status == "partial" and not output.evidence
    assert output.omitted[0].reason == "unsupported_schema"


def test_no_writes_when_data_directory_is_inside_project(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "kanvas.json").write_text('{"kanvas":1,"groups":[],"tasks":[]}')
    project = ProjectConfig(id="test", name="Test", root=str(root))
    ctx = context(root)
    output = KanvasCollector().collect(project, None, ctx)
    assert output.status == "failed"
    assert not ctx.data_dir.exists()


def test_question_dates_and_excerpt_limits(tmp_path: Path) -> None:
    project = ProjectConfig(id="test", name="Test", root=str(tmp_path / "project"))
    root = Path(project.root)
    root.mkdir()
    board = {
        "kanvas": 1,
        "groups": [],
        "tasks": [
            {
                "id": "G-01",
                "title": "Task",
                "state": "doing",
                "notes": [
                    {
                        "at": "2026-11-03T10:00:00Z",
                        "by": "codex",
                        "text": "Question: " + ("x" * 5000),
                    },
                    {"at": "not-a-date", "by": "human", "text": "unverified date"},
                ],
            }
        ],
    }
    (root / "kanvas.json").write_text(json.dumps(board))
    ctx = context(tmp_path / "service")
    ctx.limits.max_excerpt_chars = 40
    with patch("digest.collectors.kanvas.run", return_value=ProcessResult(0, "", "")):
        output = KanvasCollector().collect(project, None, ctx)
    question = next(e for e in output.evidence if e.kind == "task_question")
    assert question.event_at is not None
    assert len(question.excerpt) == 40
    assert next(e for e in output.evidence if e.excerpt == "unverified date").event_at is None
    with patch("digest.collectors.kanvas.run", return_value=ProcessResult(0, "", "")):
        filtered = KanvasCollector().collect(project, ctx.observed_at - timedelta(hours=1), ctx)
    assert not any(e.kind == "task_question" for e in filtered.evidence)


def test_reopened_task_completion_has_a_distinct_evidence_id(tmp_path: Path) -> None:
    from tests.fixtures.make_projects import _kanvas

    config = load_config(build_projects(tmp_path / "projects"))
    project = config.projects[0]
    root = Path(project.root)
    collector = KanvasCollector()
    ctx = context(tmp_path)
    ids = []
    with closing(connect(tmp_path / "digest.db")) as db:
        for state in ["done", "doing", "done"]:
            _kanvas().mutate(
                str(root / "kanvas.json"),
                lambda board, state=state: board["tasks"][0].update(state=state),
            )
            ctx.observed_at += timedelta(minutes=1)
            output = collector.collect(project, None, ctx)
            ident = persist(db, project, "kanvas", output, ctx)
            ids.append(ident)
            ctx.previous_payload = previous_payload(db, project.id, "kanvas")
            assert not collector.collect(project, None, ctx).evidence
        assert set(ids[0]).isdisjoint(ids[2])
        rows = db.execute(
            "SELECT content_hash FROM evidence WHERE kind='task_transition'"
        ).fetchall()
        assert len(rows) == 3 and len(set(rows)) == 3
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
