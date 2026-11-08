"""Source-valid numbers alone cannot certify an unsupported interpretation."""

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
from digest.llm.client import Client
from digest.llm.grounding import check
from digest.llm.router import Router
from digest.llm.validator import ValidationError, validate_report
from digest.report.builder import enrich
from digest.report.completeness import require_complete
from digest.worker import enqueue, execute
from tests.fixtures.llm import fake_response
from tests.fixtures.make_projects import build_projects
from tests.fixtures.work import add_current_work
from tests.integration.test_daily_levels import daily as daily


def wire_context(request):
    wire = json.loads(request.content)
    raw = re.search(r"<context>(.*?)</context>", wire["messages"][1]["content"], re.S).group(1)
    return wire["response_format"]["json_schema"]["schema"]["title"], json.loads(html.unescape(raw))


@pytest.mark.parametrize("repair", [True, False])
@pytest.mark.parametrize("in_question", [False, True])
def test_unsupported_status_is_repaired_once_or_stays_pending(daily, tmp_path, repair, in_question):
    config, inventory = daily
    config.projects[0].external_allowed = False
    inventory.evidence[0].excerpt = "El contraste ya se ha completado."
    source_calls = 0
    audit_calls = 0
    requests = []

    def respond(request):
        nonlocal source_calls, audit_calls
        requests.append(json.loads(request.content))
        title, package = wire_context(request)
        response = fake_response(request)
        value = json.loads(response.json()["choices"][0]["message"]["content"])
        if title == "SourceFindings":
            source_calls += 1
            text = (
                "El contraste ya se ha completado."
                if repair and package["context"].get("validation_feedback")
                else "El contraste queda pendiente."
            )
            if in_question:
                value["open_questions"] = [{"text": text, "evidence": [inventory.evidence[0].id]}]
            else:
                value["summary"]["text"] = text
        elif title == "GroundingAudit":
            audit_calls += 1
            candidate = package["context"]["candidate"]
            claims = (
                candidate.get("open_questions", [])
                if in_question
                else [candidate.get("summary", {})]
            )
            if any(c.get("text") == "El contraste queda pendiente." for c in claims):
                value = {
                    "approved": False,
                    "issues": [
                        {
                            "rule": "unsupported_claim",
                            "field": ["open_questions", 0, "text"]
                            if in_question
                            else ["summary", "text"],
                            "evidence": [inventory.evidence[0].id],
                            "source_quote": "El contraste ya se ha completado.",
                        }
                    ],
                }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    client = Client(transport=httpx.MockTransport(respond))
    with closing(connect(tmp_path / "db")) as db:
        report = enrich(db, config, deepcopy(inventory), Router(db, config, client=client))
        assert source_calls == 2
        validate_report(report, {e.id for e in report.evidence})
        assert all(w["model"] == config.llm.providers["internal"].model for w in requests)
        if repair:
            require_complete(report)
            source = report.sections["extract:res_comparison"]["sources"][0]
            corrected = source["open_questions"][0] if in_question else source["summary"]
            assert corrected["text"] == ("El contraste ya se ha completado.")
            count = len(requests)
            again = enrich(db, config, deepcopy(inventory), Router(db, config, client=client))
            require_complete(again)
            assert len(requests) == count
            check_key = "check:plan"
            tampered = deepcopy(report)
            tampered.packages[check_key]["evidence"] = []
            tampered.packages[check_key]["result_evidence"] = {
                rid: [] for rid in tampered.packages[check_key]["result_evidence"]
            }
            tampered.packages[check_key]["auxiliary_evidence"] = []
            tampered.packages[check_key]["reference_evidence"] = []
            with pytest.raises(ValidationError):
                validate_report(tampered, {e.id for e in tampered.evidence})
            tampered = deepcopy(report)
            tampered.sections["plan"]["mission"]["reason"] = "Otra justificación"
            with pytest.raises(ValidationError, match="Grounding binding"):
                validate_report(tampered, {e.id for e in tampered.evidence})
            tampered = deepcopy(report)
            del tampered.sections[check_key]
            del tampered.packages[check_key]
            with pytest.raises(ValueError):
                require_complete(tampered)
        else:
            assert audit_calls == 1, "The identical rejected candidate reuses its negative audit"
            assert not report.sections
            assert "extract:res_comparison" in report.pending
            with pytest.raises(ValueError):
                require_complete(report)
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize("mutation", ["quote", "reference", "field", "verdict"])
def test_checker_diagnostics_require_literal_sources_and_existing_fields(mutation):
    package = {
        "context": {"candidate": {"summary": "Pendiente"}},
        "evidence": [{"id": "ev", "excerpt": "Completado", "meta": {}}],
    }
    value = {
        "approved": False,
        "issues": [
            {
                "rule": "unsupported_claim",
                "field": ["summary"],
                "evidence": ["ev"],
                "source_quote": "Completado",
            }
        ],
    }
    assert not check(value, package).approved
    if mutation == "quote":
        value["issues"][0]["source_quote"] = "Fuente inventada"
    elif mutation == "reference":
        value["issues"][0]["evidence"] = ["otra"]
    elif mutation == "field":
        value["issues"][0]["field"] = ["ausente"]
    else:
        value["approved"] = True
    with pytest.raises(ValueError):
        check(value, package)


def test_unavailable_checker_keeps_worker_pending_without_publication(tmp_path, monkeypatch):
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    add_current_work(config)
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    checked = []

    def respond(request):
        title, _ = wire_context(request)
        checked.append(title)
        if title == "GroundingAudit":
            return httpx.Response(503)
        return fake_response(request)

    client = Client(transport=httpx.MockTransport(respond))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=client)

    with patch.object(Router, "__init__", setup):
        job = enqueue(config, "daily")
        path = Path(execute(config, job, now=datetime(2026, 11, 4, 19, tzinfo=UTC)))
    assert path.name == "draft.md"
    assert "GroundingAudit" in checked
    assert set(checked) <= {"SourceFindings", "GroundingAudit"}
    report = json.loads(path.with_suffix(".json").read_text())
    assert not report["sections"]
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT count(*) FROM interval WHERE closed=1").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM delivery").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM job WHERE kind='deliver'").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM plan_item").fetchone() == (0,)
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
