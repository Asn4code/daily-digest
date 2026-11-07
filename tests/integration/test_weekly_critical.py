"""New evidence can question a reviewed statement without rewriting its author."""

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
from pydantic import TypeAdapter

from digest.config import load_config
from digest.db import connect
from digest.llm.client import Client
from digest.llm.router import Router
from digest.llm.validator import ValidationError, validate_report
from digest.publish.email import compose
from digest.report.model import Report
from digest.report.render_html import render as render_html
from digest.report.render_md import render as render_md
from digest.worker import enqueue, execute
from tests.fixtures.llm import fake_response
from tests.fixtures.make_projects import _kanvas, build_projects
from tests.fixtures.work import add_current_work

ASSESSMENTS = {
    "reinforces": "El control independiente reproduce la diferencia bajo las mismas condiciones",
    "qualifies": "El efecto parece restringido a la condición analizada y no permite generalizar",
    "challenges": "El control nuevo pone en duda que la diferencia sea específica de la muestra",
    "inconclusive": "Cambian las condiciones y no se puede decidir si hay una contradicción",
}
LIMIT = "Falta separar el efecto de la condición del efecto de preparación"
FOCUS = "Contrastar ambas explicaciones con preparación independiente y condiciones comparables"


@pytest.mark.parametrize(
    "outcome,private_scope,human",
    [
        *[(value, False, True) for value in ASSESSMENTS],
        ("inconclusive", True, True),
        ("qualifies", False, False),
    ],
)
def test_weekly_critical_comparison_preserves_human_version_and_both_evidence_sides(
    tmp_path, monkeypatch, outcome, private_scope, human
):
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:2] if private_scope else config.projects[:1]
    if private_scope:
        config.projects[1].external_allowed = False
    add_current_work(config, extra_result=False)
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    calls = []

    def respond(request):
        wire = json.loads(request.content)
        title = wire["response_format"]["json_schema"]["schema"]["title"]
        calls.append(title)
        package = json.loads(
            html.unescape(
                re.search(r"<context>(.*?)</context>", wire["messages"][1]["content"], re.S).group(
                    1
                )
            )
        )
        response = fake_response(request)
        value = json.loads(response.json()["choices"][0]["message"]["content"])
        if title == "ProjectDigest" and not human:
            value["no_new_conclusion"] = False
            for card in value["results"]:
                card["meaning"] = {**card["observations"][0], "confidence": "low"}
        if title == "WeeklyCritical":
            for check in value["checks"]:
                prior = package["conclusions"][check["conclusion_id"]]
                refs = check["assessment"]["evidence"]
                check.update(
                    outcome=outcome,
                    comparable=outcome != "inconclusive",
                    assessment={
                        "text": ASSESSMENTS[outcome],
                        "evidence": refs,
                        "confidence": "low",
                    },
                    decisive_limit={"text": LIMIT, "evidence": refs},
                    focus_implication={"text": FOCUS, "evidence": refs},
                    alternative_explanations=[{"text": LIMIT, "evidence": refs}],
                )
                if outcome != "reinforces":
                    check["analyses"] = [
                        {
                            "question": "¿El efecto depende de condición o preparación?",
                            "alternatives": ["Efecto de condición", "Efecto de preparación"],
                            "required_data": (
                                "Muestra y control bajo condiciones comunes "
                                "y preparaciones independientes"
                            ),
                            "control": "Control independiente procesado con el mismo protocolo",
                            "predictions": [
                                {
                                    "alternative": "Efecto de condición",
                                    "expected_observation": "La diferencia sigue la condición",
                                },
                                {
                                    "alternative": "Efecto de preparación",
                                    "expected_observation": "La diferencia sigue la preparación",
                                },
                            ],
                            "decision_criterion": (
                                "Conservar la explicación cuya predicción se observe "
                                "al cambiar la preparación"
                            ),
                            "dependency": "Disponer del control independiente",
                            "evidence": refs,
                        }
                    ]
                assert prior["author"] == ("human" if human else "automatic")
        elif title == "WeeklyReport" and package["critical"]:
            cid = next(iter(package["critical"]))
            prior = package["conclusions"][cid]
            value["next_week"][0].update(
                project_id=prior["project_id"],
                critical_ids=[cid],
                evidence=package["critical"][cid]["new_evidence"],
                action=FOCUS,
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    original = Router.__init__
    client = Client(transport=httpx.MockTransport(respond))

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=client)

    data = Path(config.paths.data_dir)
    with patch.object(Router, "__init__", setup):
        daily = enqueue(config, "daily", params={"no_send": True})
        first_path = Path(execute(config, daily, now=datetime(2026, 11, 4, 19, tzinfo=UTC)))
        first_daily_id = json.loads(first_path.with_suffix(".json").read_text())["id"]
        with closing(connect(data / "digest.db")) as db:
            rid = db.execute(
                "SELECT id FROM result WHERE task_id='AN-01' AND project_id=?",
                (config.projects[0].id,),
            ).fetchone()[0]
            db.execute("UPDATE result SET review_state='closed_by_human' WHERE id=?", (rid,))
            db.execute(
                "INSERT INTO review(id,result_id,human_text,submitted_at,decision,decided_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    "rev_human",
                    rid,
                    json.dumps(
                        {
                            "what_shows": "La diferencia podría ser específica",
                            "scope": "Mismo protocolo; control compartido",
                        }
                    )
                    if human
                    else None,
                    "2026-11-05T10:00:00+00:00",
                    "closed",
                    "2026-11-05T10:00:00+00:00",
                ),
            )
            before = db.execute("SELECT * FROM review").fetchall()
        kanvas = _kanvas()
        kanvas.now_iso = lambda: "2026-11-06T15:00:00+00:00"

        def add(board):
            kanvas.add_note(
                kanvas.find_task(board, "AN-01"),
                ASSESSMENTS[outcome] + ". " + LIMIT,
                "fixture-agent",
            )

        kanvas.mutate(str(Path(config.projects[0].root) / "kanvas.json"), add)
        captured = enqueue(config, "capture")
        execute(config, captured, now=datetime(2026, 11, 6, 22, tzinfo=UTC))
        weekly = enqueue(config, "weekly", params={"no_send": True})
        path = Path(execute(config, weekly, now=datetime(2026, 11, 7, 9, tzinfo=UTC)))
        assert path.name == "report.md", json.loads(path.with_suffix(".json").read_text())[
            "pending"
        ]
        report = TypeAdapter(Report).validate_json(path.with_suffix(".json").read_bytes())
        validate_report(report, {e.id for e in report.evidence})
        prior = report.human_context["weekly_conclusions"][0]
        critical_key = "critical:" + config.projects[0].id
        check = report.sections[critical_key]["checks"][0]
        if private_scope:
            assert report.model_info[critical_key]["provider"] == "internal"
            assert report.model_info["weekly"]["provider"] == "internal"
        assert set(check["assessment"]["evidence"]) & set(prior["evidence"])
        assert set(check["assessment"]["evidence"]) & set(check["new_evidence"])
        assert prior["version"] == ("rev_human" if human else first_daily_id)
        assert prior["review_state"] == "closed_by_human"
        assert report.sections["weekly"]["next_week"][0]["critical_ids"] == [prior["id"]]
        with closing(connect(data / "digest.db")) as db:
            assert db.execute("SELECT * FROM review").fetchall() == before
            assert db.execute("SELECT review_state FROM result WHERE id=?", (rid,)).fetchone() == (
                "closed_by_human",
            )
            assert db.execute("SELECT count(*) FROM delivery").fetchone() == (0,)
        message = compose(config, report, path.parent)
        for text in [
            render_md(report),
            render_html(report),
            message.get_body(preferencelist=("plain",)).get_content(),
            message.get_body(preferencelist=("html",)).get_content(),
        ]:
            assert ASSESSMENTS[outcome] in text and LIMIT in text and FOCUS in text
        assert "Criterio de decisión" in path.read_text() if outcome != "reinforces" else True
        broken = deepcopy(report)
        broken.sections[critical_key]["checks"][0]["assessment"]["evidence"] = check["new_evidence"]
        with pytest.raises(ValidationError, match="lineage_missing"):
            validate_report(broken, {e.id for e in broken.evidence})
        if outcome == "inconclusive":
            broken = deepcopy(report)
            broken.sections[critical_key]["checks"][0]["outcome"] = "challenges"
            with pytest.raises(ValidationError, match="incomparable"):
                validate_report(broken, {e.id for e in broken.evidence})
        if check["analyses"]:
            broken = deepcopy(report)
            broken.sections[critical_key]["checks"][0]["analyses"][0]["predictions"][0][
                "alternative"
            ] = "Otra explicación"
            with pytest.raises(ValidationError, match="predictions_incomplete"):
                validate_report(broken, {e.id for e in broken.evidence})
            broken = deepcopy(report)
            for objective in broken.sections["weekly"]["next_week"]:
                objective["critical_ids"] = []
            with pytest.raises(ValidationError, match="critical_focus_missing"):
                validate_report(broken, {e.id for e in broken.evidence})
        # No new evidence in the next week: no repeated alert or model call.
        count = len(calls)
        again = enqueue(config, "weekly", params={"no_send": True})
        next_path = Path(execute(config, again, now=datetime(2026, 11, 14, 9, tzinfo=UTC)))
        subsequent = json.loads(next_path.with_suffix(".json").read_text())
        assert not subsequent["results"] and not subsequent["sections"]
        assert len(calls) == count
        if outcome == "reinforces" or not human:
            kanvas.now_iso = lambda: "2026-11-20T15:00:00+00:00"
            kanvas.mutate(str(Path(config.projects[0].root) / "kanvas.json"), add)
            captured = enqueue(config, "capture")
            execute(config, captured, now=datetime(2026, 11, 20, 22, tzinfo=UTC))
            next_week = enqueue(config, "weekly", params={"no_send": True})
            third = Path(execute(config, next_week, now=datetime(2026, 11, 21, 9, tzinfo=UTC)))
            later = json.loads(third.with_suffix(".json").read_text())
            statement = later["human_context"]["weekly_conclusions"][0]
            if human:
                assert statement["id"] == prior["id"]
                assert statement["version"] == "rev_human"
                assert statement["previous_comparisons"][0]["version"] == report.id
            else:
                assert statement["version"] == report.id
                assert statement["author"] == "automatic"
                assert statement["text"] == check["assessment"]["text"]
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
