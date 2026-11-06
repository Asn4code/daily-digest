"""Build and publish multi-level reports using a fake HTTP transport only."""

import json
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
from tests.fixtures.llm import fake_response
from tests.fixtures.make_projects import build_projects


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


def test_T16_total_outage_keeps_pending_inventory_without_publication(
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
    assert value["pending"]
    assert path.name == "draft.md"
    assert "Borrador pendiente" in path.read_text()
    assert not list(Path(config.paths.data_dir).glob("reports/*/*/report.*"))
    from digest.publish.deliveries import deliver_report

    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT status FROM report").fetchone() == ("generating",)
        assert db.execute("SELECT state,error FROM job").fetchone() == ("failed", "report_pending")
        assert db.execute("SELECT closed FROM interval").fetchone() == (0,)
        assert not db.execute("SELECT * FROM meta WHERE key='last_closed_daily'").fetchall()
        assert db.execute("SELECT count(*) FROM delivery").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM plan_item").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM report_evidence").fetchone()[0] == len(
            value["evidence"]
        )
        with pytest.raises(ValueError, match="not deliverable"):
            deliver_report(db, config, value["id"])
        assert db.execute("SELECT count(*) FROM delivery").fetchone() == (0,)
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
    from digest.report.render_md import render

    typed.sections["weekly"]["projects"][0]["hypotheses_changed"] = [
        {
            "text": "El control sugiere sesgo",
            "evidence": [typed.evidence[0].id],
            "confidence": "low",
        }
    ]
    assert "Interpretación (confianza low): El control sugiere sesgo" in render(typed)
    assert len(typed.sections["weekly"]["review_status"]["pending"]) > 1
    typed.sections["weekly"]["review_status"]["pending"].reverse()
    with pytest.raises(ValidationError, match="invalid_review_summary"):
        validate_report(typed, {e.id for e in typed.evidence})
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert deliver_report(db, config, value["id"], channel="obsidian") == {"obsidian": "sent"}
        assert deliver_report(db, config, value["id"], channel="drive") == {"drive": "sent"}
    assert (Path(config.paths.obsidian_vault) / "Digest/Semanal/2026-W45.md").is_file()
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize("with_sessions", [False, True])
@pytest.mark.parametrize(
    "secret",
    [
        "SYNTHETIC_PRIVATE_CREDENTIAL_7391",
        'SYNTHETIC_PRIVATE_"\\_CREDENTIAL_7391',
    ],
)
def test_secrets_are_removed_from_sources_context_snapshots_and_model_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret: str,
    with_sessions: bool,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    provider_key = "SYNTHETIC_PROVIDER_KEY_7391"
    config.email.password_env = "DIGEST_PRIVATE_TEST_PASSWORD"
    monkeypatch.setenv(config.email.password_env, secret)
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", provider_key)
    config.projects[0].objective = "Contrastar el control " + secret
    root = Path(config.projects[0].root)
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {
                "id": "secret",
                "cell_type": "code",
                "metadata": {},
                "execution_count": None,
                "source": 'api_key="' + secret + '"',
                "outputs": [],
            }
        ],
    }
    (root / "private.ipynb").write_text(json.dumps(notebook))
    sessions = root / "agent"
    sessions.mkdir()
    config.projects[0].agent_sessions = ["agent"] if with_sessions else []
    (sessions / "session.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"type": "session_meta", "payload": {"cwd": str(root), "id": secret}},
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Control verificado"}],
                    },
                },
            ]
        )
    )
    requests = []

    def respond(request):
        requests.append(request)
        return fake_response(request)

    client = Client(transport=httpx.MockTransport(respond))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=client)

    with patch.object(Router, "__init__", setup):
        job = enqueue(config, "daily", params={"no_send": True})
        path = Path(execute(config, job, now=datetime(2026, 11, 4, 19, tzinfo=UTC)))
    assert requests
    for request in requests:
        content = request.content.decode()
        forms = [secret]
        for _ in range(3):
            forms.append(json.dumps(forms[-1], ensure_ascii=False)[1:-1])
        assert all(form not in content for form in forms)
        assert provider_key not in content
    assert secret not in path.with_suffix(".json").read_text()
    for snapshot in (Path(config.paths.data_dir) / "snapshots").rglob("*.json"):
        assert secret not in snapshot.read_text()
    for artifact in (Path(config.paths.data_dir) / "nodes").rglob("*.json"):
        assert all(form not in artifact.read_text() for form in forms)
        assert provider_key not in artifact.read_text()
    for artifact in (Path(config.paths.data_dir) / "work").rglob("*.json"):
        assert all(form not in artifact.read_text() for form in forms)
        assert provider_key not in artifact.read_text()
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert secret not in repr(
            db.execute("SELECT locator,excerpt,meta FROM evidence").fetchall()
        )
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize("stage", ["extract", "conceptual", "plan", "weekly"])
def test_partial_failure_preserves_valid_sections_and_blocks_descendants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    titles = {
        "extract": "SourceFindings",
        "conceptual": "DailySynthesis",
        "plan": "TomorrowPlan",
        "weekly": "WeeklyReport",
    }
    calls = []
    failed_result = None

    def respond(request):
        nonlocal failed_result
        wire = json.loads(request.content)
        title = wire["response_format"]["json_schema"]["schema"]["title"]
        response = fake_response(request)
        value = json.loads(response.json()["choices"][0]["message"]["content"])
        calls.append(title)
        # Reject only one independent extraction; allow other results to validate.
        if title == titles[stage]:
            if stage == "extract" and failed_result is None:
                failed_result = value["result_id"]
            if stage != "extract" or value["result_id"] == failed_result:
                value["unexpected_field"] = "PRIVATE_REJECTED_BODY"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    client = Client(transport=httpx.MockTransport(respond))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=client)

    with patch.object(Router, "__init__", setup):
        job = enqueue(config, "weekly" if stage == "weekly" else "daily")
        now = (
            datetime(2026, 11, 7, 9, tzinfo=UTC)
            if stage == "weekly"
            else datetime(2026, 11, 4, 19, tzinfo=UTC)
        )
        path = Path(execute(config, job, now=now))
    value = json.loads(path.with_suffix(".json").read_text())
    key = "extract:" + failed_result if stage == "extract" else stage
    assert key in value["pending"]
    failed_key = key
    if stage == "extract":
        failed_key = next(k for k in value["source_units"][failed_result] if k in value["pending"])
    assert value["pending"][failed_key][0]["category"] == "validation"
    assert value["sections"], "Validated independent sections must survive a rejection"
    assert len(value["results"]) > 1
    assert all(r["review_state"] == "pending" for r in value["results"])
    assert "PRIVATE_REJECTED_BODY" not in path.with_suffix(".json").read_text()
    if stage == "extract":
        assert "DailySynthesis" not in calls and "TomorrowPlan" not in calls
    if stage == "conceptual":
        assert "TomorrowPlan" not in calls
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT closed FROM interval").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM delivery").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM plan_item").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM report_evidence").fetchone()[0] == len(
            value["evidence"]
        )
        errors = [json.loads(row[0]) for row in db.execute("SELECT error FROM llm_call WHERE ok=0")]
        assert all(
            e["section"] == failed_key and e["rule"] == "schema_extra_forbidden" for e in errors
        )
        assert "PRIVATE_REJECTED_BODY" not in repr(errors)
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_delivery_rechecks_completeness_even_if_status_and_flags_claim_ready(
    tmp_path: Path, valid_llm: None
) -> None:
    from digest.publish.deliveries import deliver_report

    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    job = enqueue(config, "daily", params={"no_send": True})
    path = Path(execute(config, job, now=datetime(2026, 11, 4, 19, tzinfo=UTC)))
    value = json.loads(path.with_suffix(".json").read_text())
    del value["sections"]["plan"]
    del value["packages"]["plan"]
    value["pending"] = {}
    value["mechanical"] = False
    path.with_suffix(".json").write_text(json.dumps(value))
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT status FROM report").fetchone() == ("ready",)
        with pytest.raises(ValueError, match="generation is pending"):
            deliver_report(db, config, value["id"])
        assert db.execute("SELECT count(*) FROM delivery").fetchone() == (0,)
    assert not (Path(config.paths.data_dir) / "outbox").exists()
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
