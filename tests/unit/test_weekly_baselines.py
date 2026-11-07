"""History bounds apply before copying auxiliary evidence into the inventory."""

from contextlib import closing

from digest.config import load_config
from digest.db import connect
from digest.report.conclusions import baselines
from digest.report.model import EvidenceEntry, Report, ResultEntry
from tests.fixtures.make_projects import build_projects


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
