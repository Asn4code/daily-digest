"""Build and publish multi-level reports using a fake HTTP transport only."""

import html
import json
import re
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from digest.config import load_config
from digest.db import connect
from digest.llm.client import Client
from digest.llm.router import Router
from digest.llm.validator import ValidationError, validate_report
from digest.publish.email import compose
from digest.report.model import Report
from digest.worker import enqueue, execute
from tests.fixtures.make_projects import build_projects


def fake_response(request: httpx.Request) -> httpx.Response:
    wire = json.loads(request.content)
    text = wire["messages"][1]["content"]
    package = json.loads(html.unescape(re.search(r"<context>(.*?)</context>", text, re.S).group(1)))
    entries = [
        json.loads(html.unescape(raw))
        for raw in re.findall(r'<evidence id="[^"]+">(.*?)</evidence>', text, re.S)
    ]
    eid = entries[0]["id"]
    claim = {"text": "Hay evidencia disponible para contrastar.", "evidence": [eid]}
    title = wire["response_format"]["json_schema"]["schema"]["title"]
    if title == "ResultExtraction":
        value = {
            "result_id": package["context"]["result_id"],
            "summary": claim["text"],
            "facts": [claim],
            "numbers": [],
            "interpretations": [],
            "uncertainties": [],
            "controls_and_parameters": [],
            "failures_or_blockers": [],
            "open_threads": [],
        }
    elif title == "DailySynthesis":
        value = {
            "highlights": [claim],
            "projects": [
                {
                    "project_id": pid,
                    "known_now": [claim],
                    "still_unknown": ["Falta contrastar la interpretación."],
                    "decisions_changed": [],
                    "no_new_conclusion": True,
                }
                for pid in package["project_ids"]
            ],
            "review_candidate": None,
        }
    elif title == "TomorrowPlan":
        value = {
            "mission": {
                "kind": "mission",
                "action": "Contrastar el resultado con un control",
                "done_criterion": "Explicación contrastada con las evidencias",
                "dependency": None,
                "reason": claim["text"],
                "origin": "model",
                "kanvas_task_id": None,
                "evidence": [eid],
            },
            "warmups": [],
        }
    elif title == "WeeklyReport":
        objective = {
            "kind": "mission",
            "action": "Contrastar el resultado con un control",
            "done_criterion": "Interpretación respaldada",
            "dependency": None,
            "reason": claim["text"],
            "origin": "model",
            "kanvas_task_id": None,
            "evidence": [eid],
        }
        value = {
            "projects": [
                {
                    "project_id": pid,
                    "progress_vs_objective": [claim],
                    "decisions": [],
                    "hypotheses_changed": [],
                }
                for pid in package["project_ids"]
            ],
            "patterns": [claim],
            "key_figures": [e["id"] for e in entries if e["kind"] == "figure"][:6],
            "review_status": {
                "completed": package["completed_reviews"],
                "pending": package["pending_reviews"],
                "doubts": [],
            },
            "next_week": [objective, objective, {**objective, "action": "Sesión de revisión"}],
        }
    else:
        raise AssertionError(title)
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})


def test_complete_daily_has_validated_sections_and_auditable_packages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    client = Client(transport=httpx.MockTransport(fake_response))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=client)

    with patch.object(Router, "__init__", setup):
        job = enqueue(config, "daily", params={"no_send": True})
        path = Path(execute(config, job, now=datetime(2026, 11, 4, 19, tzinfo=UTC)))
    report = json.loads(path.with_suffix(".json").read_text())
    assert {"conceptual", "plan"} <= report["sections"].keys()
    assert all("extract:" + r["id"] in report["sections"] for r in report["results"])
    assert not report["mechanical"]
    text = path.read_text()
    for section in [
        "Lo esencial",
        "Balance conceptual",
        "Todo lo hecho",
        "Plan de mañana",
        "Hilos abiertos",
        "Nivel técnico",
        "Cobertura",
    ]:
        assert section in text
    assert "Contrastar el resultado con un control" in text
    assert "No hay conclusión científica nueva" in text
    from pydantic import TypeAdapter

    typed = TypeAdapter(Report).validate_json(path.with_suffix(".json").read_bytes())
    validate_report(typed, {e.id for e in typed.evidence})
    email = compose(config, typed, path.parent)
    assert (
        "Contrastar el resultado con un control"
        in email.get_body(preferencelist=("plain",)).get_content()
    )
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT status FROM report").fetchone() == ("ready",)
        assert db.execute("SELECT accepted FROM plan_item").fetchall() == [(0,)]
        assert db.execute("SELECT count(*) FROM llm_call WHERE ok=1").fetchone()[0] >= 3
    typed.sections["conceptual"]["highlights"][0]["evidence"] = ["ev_unknown"]
    with pytest.raises(ValidationError):
        validate_report(typed, {e.id for e in typed.evidence})
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_T16_total_outage_still_publishes_all_mechanical_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    monkeypatch.delenv("DIGEST_FIXTURE_UNUSED_KEY", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    job = enqueue(config, "daily", params={"no_send": True})
    path = Path(execute(config, job, now=datetime(2026, 11, 4, 19, tzinfo=UTC)))
    value = json.loads(path.with_suffix(".json").read_text())
    assert value["mechanical"] and not value["sections"]
    assert any(r["task_id"] == "AN-01" for r in value["results"])
    assert value["warnings"]
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_T18_weekly_uses_evidence_even_when_daily_report_files_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    client = Client(transport=httpx.MockTransport(fake_response))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=client)

    with patch.object(Router, "__init__", setup):
        daily = enqueue(config, "daily", params={"no_send": True})
        daily_path = Path(execute(config, daily, now=datetime(2026, 11, 4, 19, tzinfo=UTC)))
        daily_report = json.loads(daily_path.with_suffix(".json").read_text())
        expected = {r["id"] for r in daily_report["results"]}
        daily_path.with_suffix(".json").unlink()
        daily_path.unlink()
        completed = next(r["id"] for r in daily_report["results"] if r["task_id"] == "AN-01")
        with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
            db.execute("UPDATE result SET review_state='closed_by_human' WHERE id=?", (completed,))
            db.execute(
                "INSERT INTO review(id,result_id,decision,decided_at) VALUES (?,?,?,?)",
                ("rev_fixture", completed, "closed", "2026-11-05T10:00:00+00:00"),
            )
            db.execute("UPDATE plan_item SET accepted=1,edited_text='Plan humano aceptado'")
        weekly = enqueue(config, "weekly", params={"no_send": True})
        path = Path(execute(config, weekly, now=datetime(2026, 11, 7, 9, tzinfo=UTC)))
    value = json.loads(path.with_suffix(".json").read_text())
    assert value["kind"] == "weekly" and "weekly" in value["sections"]
    assert expected <= {r["id"] for r in value["results"]}
    section = value["sections"]["weekly"]
    assert len(section["next_week"]) == 3
    assert section["review_status"]["pending"]
    assert completed in section["review_status"]["completed"]
    assert completed not in section["review_status"]["pending"]
    assert (
        value["packages"]["weekly"]["context"]["accepted_plans"][0]["edited_text"]
        == "Plan humano aceptado"
    )
    assert section["key_figures"]
    text = path.read_text()
    assert "Propuesta de semana" in text
    assert "Revisiones de la semana" in text
    assert "Patrones" in text
    assert value["start_at"] == "2026-10-30T23:00:00+00:00"
    assert value["end_at"] == "2026-11-06T23:00:00+00:00"
    from pydantic import TypeAdapter

    from digest.publish.deliveries import deliver_report

    typed = TypeAdapter(Report).validate_json(path.with_suffix(".json").read_bytes())
    validate_report(typed, {e.id for e in typed.evidence})
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert deliver_report(db, config, value["id"], channel="obsidian") == {"obsidian": "sent"}
        assert deliver_report(db, config, value["id"], channel="drive") == {"drive": "sent"}
    assert (Path(config.paths.obsidian_vault) / "Digest/Semanal/2026-W45.md").is_file()
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
