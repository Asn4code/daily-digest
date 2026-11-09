"""Exercise provider failures, repair, metadata audit and privacy without network."""

import json
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from digest.config import load_config
from digest.db import connect
from digest.llm.client import Client
from digest.llm.router import Router
from tests.fixtures.doubles import FakeLLM
from tests.fixtures.make_projects import build_projects


def test_T15_preferred_provider_down_uses_fallback_with_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    for provider in config.llm.providers.values():
        monkeypatch.setenv(provider.api_key_env, "synthetic-key")
    requests = []
    fake = FakeLLM()
    package = {
        "result_id": "res_test",
        "evidence": [{"id": "ev_test", "excerpt": "Control válido"}],
    }

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if json.loads(request.content)["model"] == config.llm.providers["internal"].model:
            return httpx.Response(503, text="PRIVATE_HTTP_BODY")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": fake.generate(package)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(
            db, config, client=Client(transport=httpx.MockTransport(respond), sleep=lambda _: None)
        )
        answer = router.generate(
            "extract",
            project_ids={config.projects[0].id},
            prompt_name="extract",
            prompt_version="1",
            messages=[{"role": "user", "content": "bounded"}],
            schema={"type": "object"},
            validate=lambda value: value,
        )
        assert answer is not None and answer.provider == "nan"
        assert len(requests) == 4
        rows = db.execute(
            "SELECT provider,model,prompt_version,ok,error,input_tokens FROM llm_call"
        ).fetchall()
        assert [r[3] for r in rows] == [0, 0, 0, 1]
        assert rows[-1][0] == "nan" and rows[-1][2] == "1" and rows[-1][5] == 10
        assert "PRIVATE_HTTP_BODY" not in repr(rows) and "synthetic-key" not in repr(rows)
        assert json.loads(requests[-1].content)["response_format"]["type"] == "json_schema"
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_T16_both_providers_down_returns_pending_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    for p in config.llm.providers.values():
        monkeypatch.setenv(p.api_key_env, "synthetic-key")
    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(
            db,
            config,
            client=Client(
                transport=httpx.MockTransport(lambda _: httpx.Response(503)), sleep=lambda _: None
            ),
        )
        assert (
            router.generate(
                "extract",
                project_ids={config.projects[0].id},
                prompt_name="extract",
                prompt_version="1",
                messages=[],
                schema=None,
                validate=lambda value: value,
            )
            is None
        )
        assert db.execute("SELECT count(*) FROM llm_call WHERE ok=0").fetchone()[0] == 6
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_one_repair_can_fix_multiple_independent_rejected_claims(tmp_path, monkeypatch):
    from digest.llm.schemas import SourceFindings
    from digest.llm.validator import EvidencePackage, validate
    from digest.report.model import EvidenceEntry

    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.extract = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    scope = EvidencePackage(
        {
            "ev_test": EvidenceEntry(
                "ev_test",
                pid,
                "metric",
                "note",
                "RMSD 1.4 Å",
                "2026-11-04T19:00:00+00:00",
                None,
                "observed",
                {},
            )
        },
        {pid},
        {"res_test"},
    )
    good = {"text": "RMSD 1.4 Å", "evidence": ["ev_test"]}
    requests = []

    def respond(request):
        wire = json.loads(request.content)
        requests.append(wire)
        repair = wire["messages"][-1]["content"] if wire["messages"] else ""
        fixed = all(field in repair for field in ("observations.0.text", "controls.0.text"))
        value = {
            "result_id": "res_test",
            "summary": good,
            "observations": [
                good if fixed else {"text": "RMSD 987654321 nm", "evidence": ["ev_test"]}
            ],
            "controls": [
                good
                if fixed
                else {"text": "<script>PRIVATE_PAYLOAD</script>", "evidence": ["ev_test"]}
            ],
            "interpretations": [],
            "limitations": [],
            "open_questions": [],
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    def check(value):
        result = SourceFindings.model_validate(value)
        validate(result, scope)
        return result

    with closing(connect(tmp_path / "db.sqlite")) as db:
        result = Router(db, config, client=Client(transport=httpx.MockTransport(respond))).generate(
            "extract",
            project_ids={pid},
            prompt_name="source",
            prompt_version="test",
            messages=[],
            schema=SourceFindings.model_json_schema(),
            validate=check,
        )
        assert result is not None and len(requests) == 2
        feedback = requests[-1]["messages"][-1]["content"]
        assert "PRIVATE_PAYLOAD" not in feedback and "987654321" not in feedback
        assert db.execute("SELECT ok FROM llm_call ORDER BY id").fetchall() == [(0,), (1,)]
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_invalid_audit_path_can_be_repaired_without_exposing_candidate(tmp_path, monkeypatch):
    from digest.llm.diagnostics import validation_issue
    from digest.llm.grounding import check
    from digest.llm.schemas import GroundingAudit

    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.contrast = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    package = {
        "evidence": [{"id": "ev_test", "excerpt": "Control válido", "meta": {}}],
        "context": {"candidate": {"observations": [{"text": "PRIVATE_CANDIDATE"}]}},
    }
    requests = []

    def respond(request):
        wire = json.loads(request.content)
        requests.append(wire)
        repair = wire["messages"][-1]["content"] if wire["messages"] else ""
        path = ["observations", 0, "text"]
        if "grounding_field_missing" not in repair:
            path = ["checks", 0, *path]
        value = {
            "approved": False,
            "issues": [
                {
                    "rule": "unsupported_claim",
                    "field": path,
                    "evidence": ["ev_test"],
                    "source_quote": "Control válido",
                }
            ],
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    schema = GroundingAudit.model_json_schema()
    with closing(connect(tmp_path / "db.sqlite")) as db:
        result = Router(db, config, client=Client(transport=httpx.MockTransport(respond))).generate(
            "contrast",
            project_ids={config.projects[0].id},
            prompt_name="grounding",
            prompt_version="test",
            messages=[],
            schema=schema,
            validate=lambda value: check(value, package),
        )
        assert result is not None and not result.value.approved
        assert len(requests) == 2
        feedback = requests[-1]["messages"][-1]["content"]
        assert "grounding_field_missing" in feedback and "PRIVATE_CANDIDATE" not in feedback
        error = json.loads(
            db.execute("SELECT error FROM llm_call ORDER BY id LIMIT 1").fetchone()[0]
        )
        assert error["rule"] == "grounding_field_missing"
    for secret in ("PRIVATE_EXCEPTION_PAYLOAD", "grounding_field_missing PRIVATE_PAYLOAD"):
        assert validation_issue(ValueError(secret), schema) == {
            "category": "validation",
            "rule": "schema_invalid",
            "field": "$",
        }
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_review_activity_is_repaired_as_model_proposal_without_human_context(tmp_path, monkeypatch):
    from digest.llm.schemas import TomorrowPlan
    from digest.llm.validator import EvidencePackage, validate
    from digest.report.model import EvidenceEntry

    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.plan = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    scope = EvidencePackage(
        {
            "ev_test": EvidenceEntry(
                "ev_test",
                pid,
                "doc_change",
                "note",
                "Control pendiente",
                "2026-11-04T19:00:00+00:00",
                None,
                "observed",
                {},
            )
        },
        {pid},
        set(),
    )
    requests = []

    def respond(request):
        wire = json.loads(request.content)
        requests.append(wire)
        repair = wire["messages"][-1]["content"] if wire["messages"] else ""
        value = {
            "mission": None,
            "carry_forward_id": None,
            "change_reason": None,
            "no_mission_reason": {"text": "Solo preparar la revisión", "evidence": ["ev_test"]},
            "warmups": [
                {
                    "kind": "warmup",
                    "project_id": pid,
                    "action": "Revisar el control",
                    "done_criterion": "Control contrastado",
                    "dependency": None,
                    "reason": "Preparar la revisión",
                    "origin": "model" if "origin=model" in repair else "review",
                    "kanvas_task_id": None,
                    "evidence": ["ev_test"],
                }
            ],
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    def check(value):
        result = TomorrowPlan.model_validate(value)
        validate(result, scope)
        return result

    with closing(connect(tmp_path / "db.sqlite")) as db:
        result = Router(db, config, client=Client(transport=httpx.MockTransport(respond))).generate(
            "plan",
            project_ids={pid},
            prompt_name="plan",
            prompt_version="test",
            messages=[],
            schema=TomorrowPlan.model_json_schema(),
            validate=check,
        )
        assert result is not None and result.value.warmups[0].origin == "model"
        assert len(requests) == 2 and not scope.has_human_context
        assert db.execute("SELECT count(*) FROM review").fetchone()[0] == 0
        error = json.loads(
            db.execute("SELECT error FROM llm_call ORDER BY id LIMIT 1").fetchone()[0]
        )
        assert error["rule"] == "human_review_origin_missing"
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_private_project_never_reaches_external_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects[0].external_allowed = False
    for p in config.llm.providers.values():
        monkeypatch.setenv(p.api_key_env, "synthetic-key")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(401, text="PRIVATE_SECRET")

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        assert (
            router.generate(
                "conceptual",
                project_ids={config.projects[0].id},
                prompt_name="conceptual",
                prompt_version="1",
                messages=[],
                schema=None,
                validate=lambda value: value,
            )
            is None
        )
        assert len(requests) == 1
        assert db.execute("SELECT DISTINCT provider FROM llm_call").fetchall() == [("internal",)]
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_broken_json_gets_one_repair_and_no_raw_error_in_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    monkeypatch.setenv(config.llm.providers["internal"].api_key_env, "synthetic-key")
    fake = FakeLLM("broken_json")
    package = {"result_id": "res_test", "evidence": []}
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": fake.generate(package)}}]}
        )

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        assert (
            router.generate(
                "extract",
                project_ids={config.projects[0].id},
                prompt_name="extract",
                prompt_version="1",
                messages=[],
                schema=None,
                validate=lambda value: value,
            )
            is not None
        )
        assert len(requests) == 2
        assert len(json.loads(requests[1].content)["messages"]) == 1
        rows = db.execute("SELECT ok,error FROM llm_call").fetchall()
        assert rows[0][0] == 0 and json.loads(rows[0][1])["rule"] == "invalid_json"
        assert rows[1] == (1, None)
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize("failure", ["semantic", "schema", "extra"])
def test_validation_diagnostics_and_repair_include_safe_rule_and_field_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from digest.llm.schemas import ResultExtraction
    from digest.llm.validator import EvidencePackage, validate
    from digest.report.model import EvidenceEntry

    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.extract = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    package = {
        "result_id": "res_test",
        "evidence": [{"id": "ev_test", "excerpt": "Control válido"}],
    }
    value = json.loads(FakeLLM().generate(package))
    private = "PRIVATE_EXCEPTION_PAYLOAD"
    if failure == "semantic":
        value["facts"][0]["text"] = "Medida 987654321 Å"
        expected = ("unsupported_number", "facts.0.text")
    elif failure == "schema":
        value["facts"][0]["text"] = {"private": private}
        expected = ("schema_string_type", "facts.0.text")
    else:
        value[private] = private
        expected = ("schema_extra_forbidden", "<extra>")
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    scope = EvidencePackage(
        {
            "ev_test": EvidenceEntry(
                "ev_test",
                config.projects[0].id,
                "doc_change",
                "note",
                "Control válido",
                "2026-11-04T19:00:00+00:00",
                None,
                "observed",
                {},
            )
        },
        {config.projects[0].id},
        {"res_test"},
    )

    def check(value):
        parsed = ResultExtraction.model_validate(value)
        validate(parsed, scope)
        return parsed

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        assert (
            router.generate(
                "extract",
                project_ids=scope.project_ids,
                prompt_name="extract",
                prompt_version="1",
                messages=[],
                schema=ResultExtraction.model_json_schema(),
                validate=check,
                section="extract:res_test",
            )
            is None
        )
        errors = [json.loads(row[0]) for row in db.execute("SELECT error FROM llm_call")]
        assert len(errors) == 2
        assert all((e["rule"], e["field"]) == expected for e in errors)
        assert all(e["stage"] == "extract" and e["section"] == "extract:res_test" for e in errors)
        repair = requests[1]["messages"][-1]["content"]
        assert expected[0] in repair and expected[1] in repair
        assert private not in repr(errors) + repair
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize("failure", ["timeout", "deadline", "source"])
def test_timeout_and_input_diagnostics_are_distinct_from_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import time

    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.extract = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    if failure == "source":
        monkeypatch.delenv("DIGEST_FIXTURE_UNUSED_KEY")
    requests = []

    def respond(request):
        requests.append(request)
        raise httpx.ReadTimeout("PRIVATE_TIMEOUT_BODY", request=request)

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(
            db,
            config,
            client=Client(transport=httpx.MockTransport(respond), sleep=lambda _: None),
            deadline=time.monotonic() - 1 if failure == "deadline" else None,
        )
        assert (
            router.generate(
                "extract",
                project_ids={config.projects[0].id},
                prompt_name="extract",
                prompt_version="1",
                messages=[],
                schema=None,
                validate=lambda v: v,
            )
            is None
        )
        errors = [json.loads(r[0]) for r in db.execute("SELECT error FROM llm_call")]
        rule = {
            "timeout": "provider_timeout",
            "deadline": "generation_timeout",
            "source": "credential_missing",
        }[failure]
        assert errors and all(e["rule"] == rule for e in errors)
        assert all(
            e["category"] == ("provider" if failure == "source" else "timeout") for e in errors
        )
        assert len(requests) == (3 if failure == "timeout" else 0)
        assert "PRIVATE_TIMEOUT_BODY" not in repr(errors)
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
