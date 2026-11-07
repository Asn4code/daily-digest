"""Daily meaning survives channel changes; history and human intent stay separate."""

import html
import json
import re
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from digest.config import load_config
from digest.db import connect
from digest.llm import schemas
from digest.llm.client import Client
from digest.llm.router import Router
from digest.llm.validator import EvidencePackage, ValidationError, validate, validate_report
from digest.publish.email import compose
from digest.report.builder import enrich
from digest.report.completeness import require_complete
from digest.report.model import Coverage, EvidenceEntry, Report, ResultEntry
from digest.report.render_html import render as render_html
from digest.report.render_md import render as render_md
from digest.worker import enqueue, execute
from tests.fixtures.llm import fake_response
from tests.fixtures.make_projects import build_projects
from tests.fixtures.work import add_current_work

NOW = "2026-11-04T19:00:00+00:00"
OBSERVATION = "La diferencia aparece al comparar muestra y control con el mismo protocolo"
MEANING = "El efecto podría depender de la condición y requiere contraste independiente"
LIMIT = "El control comparte preparación con la muestra y no descarta un sesgo común"


@pytest.fixture
def daily(tmp_path, monkeypatch):
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    evidence = EvidenceEntry(
        "ev_comparison",
        pid,
        "task_note",
        "notes/comparison.md",
        ". ".join([OBSERVATION, MEANING, LIMIT]),
        NOW,
        NOW,
        "event",
        {"capture_origin": "dated_event"},
    )
    report = Report(
        "rep_levels",
        "daily",
        "2026-11-03T19:00:00+00:00",
        NOW,
        NOW,
        evidence=[evidence],
        results=[
            ResultEntry(
                "res_comparison", pid, "Comparación con control", None, "pending", [evidence.id]
            )
        ],
        coverage=[Coverage(1, pid, "notes", "ok", [])],
    )
    yield config, report
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def response_with_meaning(request):
    response = fake_response(request)
    value = json.loads(response.json()["choices"][0]["message"]["content"])
    title = json.loads(request.content)["response_format"]["json_schema"]["schema"]["title"]
    claim = {"text": OBSERVATION, "evidence": ["ev_comparison"]}
    meaning = {"text": MEANING, "evidence": ["ev_comparison"], "confidence": "low"}
    limit = {"text": LIMIT, "evidence": ["ev_comparison"]}
    if title == "SourceFindings":
        value.update(
            summary=claim,
            observations=[claim],
            interpretations=[meaning],
            controls=[limit],
            limitations=[limit],
        )
    elif title == "ProjectDigest":
        value.update(
            explanation=claim, importance=meaning, known_now=[claim], still_unknown=[limit]
        )
        value["results"][0].update(
            observations=[claim], meaning=meaning, controls=[limit], limits=[limit]
        )
    elif title == "DailyOverview":
        value["highlights"][0].update(observation=claim, meaning=meaning, decisive_limit=limit)
    elif title == "TomorrowPlan":
        value.update(mission=None, no_mission_reason=limit)
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})


def test_meaning_and_decisive_limit_survive_all_channels_without_forcing_mission(daily, tmp_path):
    config, report = daily
    with closing(connect(tmp_path / "db")) as db:
        enrich(
            db,
            config,
            report,
            Router(db, config, client=Client(transport=httpx.MockTransport(response_with_meaning))),
        )
        require_complete(report)
        validate_report(report, {e.id for e in report.evidence})
        assert db.execute("SELECT count(*) FROM plan_item").fetchone() == (0,)
    message = compose(config, report, tmp_path)
    outputs = [
        render_md(report),
        render_html(report),
        message.get_body(preferencelist=("plain",)).get_content(),
        message.get_body(preferencelist=("html",)).get_content(),
    ]
    for output in outputs:
        assert all(text in output for text in [OBSERVATION, MEANING, LIMIT])
        assert "Sin misión nueva propuesta" in output
        assert "Comparación con control" in output
    assert "[!info]-" in outputs[0]
    assert "<details" in outputs[1]
    assert report.results[0].review_state == "pending"
    tampered = deepcopy(report)
    tampered.sections["project:" + config.projects[0].id]["results"] = []
    with pytest.raises(ValueError):
        validate_report(tampered, {e.id for e in tampered.evidence})
    tampered = deepcopy(report)
    tampered.results[0].reference_only = True
    with pytest.raises(ValidationError, match="activity role"):
        validate_report(tampered, {e.id for e in tampered.evidence})


def test_initial_inventory_remains_visible_without_model_work(daily, tmp_path):
    config, report = daily
    report.evidence[0].event_at = None
    report.evidence[0].time_quality = "observed"
    report.evidence[0].meta["capture_origin"] = "initial_inventory"
    requests = []

    def respond(request):
        requests.append(request)
        return fake_response(request)

    with closing(connect(tmp_path / "db")) as db:
        enrich(
            db,
            config,
            report,
            Router(db, config, client=Client(transport=httpx.MockTransport(respond))),
        )
    require_complete(report)
    validate_report(report, {e.id for e in report.evidence})
    assert not requests and not report.sections
    assert report.results[0].reference_only
    assert "Comparación con control" in render_md(report)
    assert "no acredita trabajo nuevo" in render_md(report)
    assert "Sin novedades verificadas" in render_md(report)
    report.coverage[0].status = "partial"
    with pytest.raises(ValueError, match="pending"):
        require_complete(report)


def test_latest_anchor_is_complete_and_empty_highlights_do_not_claim_no_activity(daily, tmp_path):
    config, report = daily
    latest = deepcopy(report.evidence[0])
    latest.id = "ev_latest"
    latest.event_at = "2026-11-04T19:00:00+00:00"
    report.evidence[0].event_at = "2026-11-04T18:00:00+00:00"
    latest.excerpt = (
        "Preparación y condiciones documentadas. " * 9 + "Lanzamiento declarado; sin cosecha."
    )
    report.evidence.append(latest)
    report.results[0].evidence.append(latest.id)
    requests = []

    def respond(request):
        wire = json.loads(request.content)
        title = wire["response_format"]["json_schema"]["schema"]["title"]
        if title == "ProjectDigest":
            requests.append(wire)
        response = fake_response(request)
        value = json.loads(response.json()["choices"][0]["message"]["content"])
        if title == "DailyOverview":
            value["highlights"] = []
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    with closing(connect(tmp_path / "db")) as db:
        enrich(
            db,
            config,
            report,
            Router(db, config, client=Client(transport=httpx.MockTransport(respond))),
        )
    require_complete(report)
    wire_text = requests[0]["messages"][1]["content"]
    anchors = [
        json.loads(html.unescape(raw))
        for raw in re.findall(r'<evidence id="[^"]+">(.*?)</evidence>', wire_text, re.S)
    ]
    anchor = next(e for e in anchors if e["id"] == latest.id)
    assert anchor["excerpt"] == latest.excerpt
    assert anchor["event_at"] == latest.event_at
    assert anchor["excerpt_included"] is True
    assert not any("excerpt" in e for e in anchors if e["id"] != latest.id)
    message = compose(config, report, tmp_path)
    for text in [
        render_md(report),
        render_html(report),
        message.get_body(preferencelist=("plain",)).get_content(),
        message.get_body(preferencelist=("html",)).get_content(),
    ]:
        assert "Hay resultados del intervalo" in text
        assert "Sin novedades verificadas" not in text


@pytest.mark.parametrize("state", ["done", "review", "blocked"])
def test_plan_checks_task_state_within_project_namespace(state):
    evidence = EvidenceEntry("ev", "p", "task_note", "note", "Hay evidencia", NOW, NOW, "event", {})
    scope = EvidencePackage(
        {"ev": evidence},
        {"p", "other"},
        set(),
        {"AN-01": "todo"},
        project_task_states={"p": {"AN-01": state}, "other": {"AN-01": "todo"}},
    )
    mission = dict(
        kind="mission",
        project_id="p",
        action="Contrastar",
        done_criterion="Contraste documentado",
        dependency=None,
        reason="Hay evidencia",
        origin="kanvas",
        kanvas_task_id="AN-01",
        evidence=["ev"],
        priority_basis=["kanvas"],
        decision_unlocked=None,
        uncertainty_addressed=None,
        human_plan_id=None,
    )
    value = schemas.TomorrowPlan(
        mission=schemas.DailyMission(**mission),
        warmups=[],
        carry_forward_id=None,
        change_reason=None,
        no_mission_reason=None,
    )
    with pytest.raises(ValidationError):
        validate(value, scope)
    scope.project_task_states["p"]["AN-01"] = "todo"
    validate(value, scope)
    scope.human_plan_ids = {3}
    with pytest.raises(ValidationError, match="change_unjustified"):
        validate(value, scope)
    value.change_reason = schemas.Claim(text="Hay evidencia", evidence=["ev"])
    validate(value, scope)


def test_accepted_human_edit_is_carried_without_overwriting_or_new_proposal(daily):
    config, _ = daily
    add_current_work(config, extra_result=False)
    client = Client(transport=httpx.MockTransport(fake_response))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=client)

    data = Path(config.paths.data_dir)
    with patch.object(Router, "__init__", setup):
        job = enqueue(config, "daily", params={"no_send": True})
        execute(config, job, now=datetime(2026, 11, 4, 19, tzinfo=UTC))
        with closing(connect(data / "digest.db")) as db:
            db.execute(
                "UPDATE plan_item SET accepted=1,edited_text=?", ("Mi foco humano <seguro>",)
            )
            before = db.execute("SELECT * FROM plan_item").fetchall()
        (Path(config.projects[0].root) / "new_control.md").write_text(
            "Control adicional pendiente de contraste"
        )
        second = enqueue(config, "daily", params={"no_send": True})
        path = Path(execute(config, second, now=datetime(2026, 11, 5, 19, tzinfo=UTC)))
    value = json.loads(path.with_suffix(".json").read_text())
    assert value["sections"]["plan"]["carry_forward_id"] == before[0][0]
    assert value["sections"]["plan"]["mission"] is None
    assert "Mi foco humano &lt;seguro&gt;" in path.with_suffix(".html").read_text()
    assert "Se conserva el plan aceptado" in path.read_text()
    with closing(connect(data / "digest.db")) as db:
        assert db.execute("SELECT * FROM plan_item").fetchall() == before


def test_plan_bounds_current_doubts_without_deleting_or_reviving_old_reviews(daily, tmp_path):
    config, report = daily
    project = config.projects[0]
    with closing(connect(tmp_path / "db")) as db:
        db.execute(
            "INSERT INTO project VALUES (?,?,?,?,?,?,?)",
            (project.id, project.name, project.root, project.objective, 1, 1, "fixture"),
        )
        for n in range(42):
            rid = f"res_doubt_{n:02d}"
            db.execute(
                "INSERT INTO result(id,project_id,title,first_seen_at) VALUES (?,?,?,?)",
                (rid, project.id, "Pregunta", NOW),
            )
            db.execute(
                "INSERT INTO review(id,result_id,submitted_at,doubts) VALUES (?,?,?,?)",
                (f"rev_{n:02d}", rid, NOW, json.dumps(["Duda vigente"])),
            )
        db.execute(
            "INSERT INTO review(id,result_id,submitted_at,doubts) VALUES (?,?,?,?)",
            ("rev_new", "res_doubt_41", "2026-11-04T19:01:00+00:00", "[]"),
        )
        enrich(
            db,
            config,
            report,
            Router(db, config, client=Client(transport=httpx.MockTransport(fake_response))),
        )
        require_complete(report)
        doubts = report.packages["plan"]["context"]["human_doubts"]
        assert len(doubts) == 40
        assert "res_doubt_41" not in {d["result_id"] for d in doubts}
        assert any("dudas vigentes" in warning for warning in report.warnings)
        assert db.execute("SELECT count(*) FROM review").fetchone() == (43,)
