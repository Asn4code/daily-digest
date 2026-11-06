"""Grouping preserves human state; intervals follow local calendar and publication."""

from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from digest.collectors.base import CaptureContext, CollectorOutput, EvidenceDraft
from digest.collectors.store import persist
from digest.config import ProjectConfig
from digest.db import connect
from digest.intervals import close_interval, open_interval, pending_days
from digest.results import group_results


def test_grouping_preserves_review_and_links_explicit_references(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = ProjectConfig(id="p", name="P", root=str(root))
    now = datetime(2026, 11, 4, 18, tzinfo=UTC)
    ctx = CaptureContext(tmp_path / "service", now)
    output = CollectorOutput(
        evidence=[
            EvidenceDraft(
                "task_transition",
                "AN-01#state",
                "done",
                "Task",
                now,
                meta={"title": "Result", "state": "done"},
                task_id="AN-01",
            ),
            EvidenceDraft(
                "task_note",
                "AN-01#note",
                "note",
                "See results/scores.csv",
                now,
                meta={"title": "Result", "state": "done"},
                task_id="AN-01",
            ),
            EvidenceDraft("commit", "a" * 40, "commit", "AN-01 Implement comparison", now, now),
            EvidenceDraft(
                "metric", "metric", "score", "score", now, meta={"path": "results/scores.csv"}
            ),
            EvidenceDraft(
                "doc_change", "README.md", "doc", "README", now, meta={"path": "README.md"}
            ),
        ]
    )
    with closing(connect(tmp_path / "db")) as db:
        persist(db, project, "test", output, ctx)
        group_results(db)
        assert db.execute("SELECT count(*) FROM result").fetchone() == (2,)
        assert db.execute(
            "SELECT count(*) FROM result_evidence WHERE result_id=?", ("res_p_AN-01",)
        ).fetchone() == (4,)
        # Simulate a human decision; grouping must preserve it.
        db.execute("UPDATE result SET review_state='closed_by_human' WHERE id='res_p_AN-01'")
        group_results(db)
        assert db.execute("SELECT review_state FROM result WHERE id='res_p_AN-01'").fetchone() == (
            "closed_by_human",
        )
        assert db.execute("SELECT count(*) FROM result_evidence").fetchone() == (5,)


def published(db, interval) -> str:
    name = f"report_{interval.id}"
    db.execute(
        "INSERT INTO report(id,interval_id,revision,status,created_at) VALUES (?,?,1,'ready',?)",
        (name, interval.id, interval.end.isoformat()),
    )
    close_interval(db, interval.id, name)
    return name


def test_daily_preview_and_automatic_skip(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "db")) as db:
        now = datetime(2026, 11, 4, 19, tzinfo=UTC)
        daily = open_interval(db, now)
        assert daily.start == datetime(2026, 11, 3, 23, tzinfo=UTC)
        with pytest.raises(ValueError):
            close_interval(db, daily.id, "missing")
        published(db, daily)
        preview = open_interval(db, now + timedelta(hours=1), kind="preview")
        published(db, preview)
        assert db.execute("SELECT closed FROM interval WHERE id=?", (preview.id,)).fetchone() == (
            0,
        )
        assert open_interval(db, now + timedelta(hours=1), requested_by="timer") is None
        assert open_interval(db, now + timedelta(days=1), requested_by="timer") is not None


def test_weekly_boundaries_include_dst_transition(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "db")) as db:
        weekly = open_interval(
            db, datetime(2026, 10, 31, 9, tzinfo=UTC), kind="weekly", requested_by="timer"
        )
        assert weekly.start == datetime(2026, 10, 23, 22, tzinfo=UTC)
        assert weekly.end == datetime(2026, 10, 30, 23, tzinfo=UTC)
        assert weekly.end - weekly.start == timedelta(hours=169)


def test_pending_days_only_with_uncovered_evidence(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = ProjectConfig(id="p", name="P", root=str(root))
    at = datetime(2026, 11, 2, 10, tzinfo=UTC)
    with closing(connect(tmp_path / "db")) as db:
        persist(
            db,
            project,
            "test",
            CollectorOutput(evidence=[EvidenceDraft("metric", "score", "1", "1", at)]),
            CaptureContext(tmp_path / "service", at),
        )
        pending = pending_days(db, datetime(2026, 11, 4, 10, tzinfo=UTC))
        assert len(pending) == 1
        interval = open_interval(db, pending[0][1], since=pending[0][0], until=pending[0][1])
        published(db, interval)
        assert not pending_days(db, datetime(2026, 11, 4, 10, tzinfo=UTC))


def test_pending_windows_reserve_time_and_reject_partial_overlap(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "db")) as db:
        first_end = datetime(2026, 11, 4, 19, tzinfo=UTC)
        first = open_interval(db, first_end)
        db.execute(
            "INSERT INTO report(id,interval_id,revision,status,created_at) "
            "VALUES ('pending',?,1,'generating',?)",
            (first.id, first_end.isoformat()),
        )
        following = open_interval(db, first_end + timedelta(days=1))
        assert following.start == first.end
        assert db.execute("SELECT closed FROM interval WHERE id=?", (first.id,)).fetchone() == (0,)
        with pytest.raises(ValueError, match="overlaps"):
            open_interval(db, first_end + timedelta(days=1), since=first.start + timedelta(hours=1))
        # An exact interval is a revision, never a partially overlapping new window.
        revision = open_interval(
            db, first_end + timedelta(days=1), since=first.start, until=first.end
        )
        assert revision.start == first.start and revision.end == first.end


def test_recovery_queues_only_gaps_outside_reserved_windows(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = ProjectConfig(id="p", name="P", root=str(root))
    start = datetime(2026, 11, 2, 10, tzinfo=UTC)
    with closing(connect(tmp_path / "db")) as db:
        for hour in (9, 13, 19):
            at = start.replace(hour=hour)
            persist(
                db,
                project,
                "test",
                CollectorOutput(
                    evidence=[EvidenceDraft("metric", str(hour), str(hour), "Observed", at)]
                ),
                CaptureContext(tmp_path / "service", at),
            )
        reserved = open_interval(
            db, start + timedelta(hours=6), since=start, until=start + timedelta(hours=6)
        )
        db.execute(
            "INSERT INTO report(id,interval_id,revision,status,created_at) "
            "VALUES ('pending',?,1,'generating',?)",
            (reserved.id, start.isoformat()),
        )
        gaps = pending_days(db, datetime(2026, 11, 4, 10, tzinfo=UTC))
        assert len(gaps) == 2
        assert gaps[0][1] == reserved.start
        assert gaps[1][0] == reserved.end
        assert all(max(first, reserved.start) >= min(last, reserved.end) for first, last in gaps)


def test_late_evidence_keeps_event_time_and_is_reserved_as_historical_context(
    tmp_path: Path,
) -> None:
    from digest.report.mechanical import build

    root = tmp_path / "project"
    root.mkdir()
    project = ProjectConfig(id="p", name="P", root=str(root))
    first_end = datetime(2026, 11, 2, 19, tzinfo=UTC)
    observed = first_end + timedelta(days=1)
    original_event = first_end - timedelta(hours=1)
    with closing(connect(tmp_path / "db")) as db:
        previous = open_interval(db, first_end)
        published(db, previous)
        late = EvidenceDraft(
            "commit",
            "late",
            "newly discovered",
            "Evento anterior descubierto después",
            observed,
            original_event,
        )
        ids = persist(
            db,
            project,
            "test",
            CollectorOutput(evidence=[late]),
            CaptureContext(tmp_path / "service", observed),
        )
        group_results(db)
        interval = open_interval(db, observed)
        report = build(db, interval, "late_report", observed)
        assert [e.id for e in report.evidence] == ids
        assert report.evidence[0].event_at == original_event.isoformat()
        assert report.evidence[0].meta["report_role"] == "historical_reference"
        assert report.evidence[0].observed_at == observed.isoformat()
