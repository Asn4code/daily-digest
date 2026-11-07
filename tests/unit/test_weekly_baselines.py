"""History bounds apply before copying auxiliary evidence into the inventory."""

from contextlib import closing

import pytest

from digest.config import load_config
from digest.db import connect
from digest.report.conclusions import baselines
from digest.report.model import EvidenceEntry, Report, ResultEntry
from tests.fixtures.make_projects import build_projects


@pytest.mark.parametrize("human_after_window", [False, True])
def test_latest_human_version_prevents_rescuing_a_superseded_statement(
    tmp_path, human_after_window
):
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    project = config.projects[0]
    times = {n: f"2026-11-0{n}T10:00:00+00:00" for n in range(1, 9)}
    report = Report(
        "rep_latest",
        "weekly",
        times[1],
        times[8],
        times[8],
        evidence=[
            EvidenceEntry(
                "ev_new",
                project.id,
                "task_note",
                "new",
                "Control nuevo",
                times[6],
                times[6],
                "event",
                {},
            )
        ],
        results=[ResultEntry("res", project.id, "Resultado", None, "closed_by_human", ["ev_new"])],
    )
    if human_after_window:
        report.end_at = times[6]
    with closing(connect(tmp_path / "db")) as db:
        db.execute(
            "INSERT INTO project VALUES (?,?,?,?,?,?,?)",
            (project.id, project.name, project.root, project.objective, 1, 1, "fixture"),
        )
        db.execute(
            "INSERT INTO result(id,project_id,title,first_seen_at) VALUES (?,?,?,?)",
            ("res", project.id, "Resultado", times[4]),
        )
        for eid, day in [("ev_old", 4), ("ev_new", 6)]:
            db.execute(
                "INSERT INTO evidence(id,project_id,source,kind,locator,observed_at,event_at,"
                "time_quality,content_hash,excerpt) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    eid,
                    project.id,
                    "notes",
                    "task_note",
                    eid,
                    times[day],
                    times[day],
                    "event",
                    eid,
                    "Fuente",
                ),
            )
            db.execute("INSERT INTO result_evidence VALUES (?,?)", ("res", eid))
        for review_id, day in [("rev_old", 5), ("rev_latest", 7)]:
            db.execute(
                "INSERT INTO review(id,result_id,human_text,submitted_at) VALUES (?,?,?,?)",
                (review_id, "res", "Explicación " + review_id, times[day]),
            )
        before = db.execute("SELECT * FROM review").fetchall()
        assert baselines(db, config, report, project.id) == []
        assert report.human_context["weekly_history"][project.id]["without_new_evidence"] == ["res"]
        report.evidence.append(
            EvidenceEntry(
                "ev_after",
                project.id,
                "task_note",
                "after",
                "Otra evidencia posterior",
                times[8],
                times[8],
                "event",
                {},
            )
        )
        report.results[0].evidence.append("ev_after")
        report.end_at = times[8]
        selected = baselines(db, config, report, project.id)
        assert selected[0]["version"] == "rev_latest"
        assert selected[0]["new_evidence"] == ["ev_after"]
        assert db.execute("SELECT * FROM review").fetchall() == before
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_history_cap_does_not_copy_unselected_sources(tmp_path):
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    project = config.projects[0]
    older = "2026-11-04T10:00:00+00:00"
    reviewed = "2026-11-05T10:00:00+00:00"
    now = "2026-11-06T10:00:00+00:00"
    report = Report("rep_bound", "weekly", reviewed, now, now)
    with closing(connect(tmp_path / "db")) as db:
        db.execute(
            "INSERT INTO project VALUES (?,?,?,?,?,?,?)",
            (project.id, project.name, project.root, project.objective, 1, 1, "fixture"),
        )
        for n in range(21):
            rid, old, new = f"res_{n}", f"ev_old_{n}", f"ev_new_{n}"
            db.execute(
                "INSERT INTO result(id,project_id,title,first_seen_at) VALUES (?,?,?,?)",
                (rid, project.id, "Resultado", older),
            )
            db.execute(
                "INSERT INTO evidence(id,project_id,source,kind,locator,observed_at,event_at,"
                "time_quality,content_hash,excerpt) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    old,
                    project.id,
                    "notes",
                    "task_note",
                    old,
                    older,
                    older,
                    "event",
                    old,
                    "Conclusión previa",
                ),
            )
            db.execute("INSERT INTO result_evidence VALUES (?,?)", (rid, old))
            db.execute(
                "INSERT INTO review(id,result_id,human_text,submitted_at) VALUES (?,?,?,?)",
                (f"rev_{n}", rid, "Declaración humana", reviewed),
            )
            report.evidence.append(
                EvidenceEntry(
                    new, project.id, "task_note", new, "Control nuevo", now, now, "event", {}
                )
            )
            report.results.append(ResultEntry(rid, project.id, "Resultado", None, "pending", [new]))
        prior = baselines(db, config, report, project.id)
    assert len(prior) == 20
    assert len(report.results) == 21
    assert sum(e.context_only for e in report.evidence) == 20
    assert any("veinte" in warning for warning in report.warnings)
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
