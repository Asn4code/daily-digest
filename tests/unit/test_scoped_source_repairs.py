"""Scoped claim-level repair contracts, adversarial rejections and grounding checks."""

import json
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from digest.config import load_config
from digest.db import connect
from digest.llm import schemas
from digest.llm.client import Client, ClientError, json_object
from digest.llm.contracts import evidence_schema
from digest.llm.router import Router
from digest.llm.source_repair import plan_source_repair
from digest.llm.validator import EvidencePackage, ValidationError, validate, validate_report
from digest.report.builder import enrich
from digest.report.completeness import require_complete
from digest.report.model import EvidenceEntry, Report, ResultEntry
from tests.fixtures.llm import fake_response
from tests.fixtures.make_projects import build_projects


def _scope(project_id: str) -> tuple[EvidencePackage, dict[str, str]]:
    entries = {
        "ev_ok": EvidenceEntry(
            "ev_ok",
            project_id,
            "metric",
            "note",
            "RMSD 1.4 Å y 4 filas observadas; control pendiente.",
            "2026-11-04T19:00:00+00:00",
            None,
            "observed",
            {"capture_origin": "observed_change"},
        ),
        "ev_extra": EvidenceEntry(
            "ev_extra",
            project_id,
            "doc_change",
            "docs/control.md",
            "Se registró 206 de 206 (9WKV_A terminada).",
            "2026-11-04T19:05:00+00:00",
            None,
            "observed",
            {"path": "docs/control.md", "capture_origin": "observed_change"},
        ),
    }
    return EvidencePackage(entries, {project_id}, {"res_test"}), {
        "ok_rmsd": "RMSD 1.4 Å.",
        "ok_rows": "Se observaron 4 filas.",
        "ok_interp": "El resultado sigue condicionado al control pendiente.",
        "ok_ratio": "Se cita «206 de 206 (9WKV_A terminada)», sin cierre independiente.",
    }


def _candidate(claims: dict[str, str]) -> dict[str, object]:
    return {
        "result_id": "res_test",
        "summary": {"text": claims["ok_rmsd"], "evidence": ["ev_ok"]},
        "observations": [
            {"text": claims["ok_rows"], "evidence": ["ev_ok"]},
            {"text": "Medida inventada 999 nm.", "evidence": ["ev_ok"]},
        ],
        "interpretations": [
            {"text": claims["ok_interp"], "evidence": ["ev_ok"], "confidence": "medium"}
        ],
        "controls": [{"text": claims["ok_rmsd"], "evidence": ["ev_ok"]}],
        "limitations": [{"text": claims["ok_interp"], "evidence": ["ev_ok"]}],
        "open_questions": [{"text": claims["ok_interp"], "evidence": ["ev_ok"]}],
    }


def _validate_source(scope: EvidencePackage):
    def check(value: dict[str, object]) -> schemas.SourceFindings:
        parsed = schemas.SourceFindings.model_validate(value)
        validate(parsed, scope)
        return parsed

    return check


def test_scoped_repair_preserves_valid_claims_and_list_lengths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.extract = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    scope, claims = _scope(pid)
    initial = _candidate(claims)
    source_schema = evidence_schema(schemas.SourceFindings, set(scope.evidence))
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        requests.append(wire)
        schema_info = wire["response_format"]["json_schema"]["schema"]
        if schema_info["title"] == "SourceFindings":
            body: dict[str, object] = initial
        else:
            assert schema_info["title"] == "SourceClaimRepair"
            tids = list(schema_info["properties"])
            assert len(tids) == 1
            body = {tids[0]: {"text": claims["ok_ratio"], "evidence": ["ev_extra"]}}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        result = router.generate(
            "extract",
            project_ids={pid},
            prompt_name="source",
            prompt_version="test",
            messages=[{"role": "user", "content": "source package"}],
            schema=source_schema,
            validate=_validate_source(scope),
            section="extract:res_test",
        )
        assert result is not None and len(requests) == 2
        repair_wire = json.dumps(requests[1]["messages"], ensure_ascii=False)
        assert claims["ok_rows"] not in repair_wire
        assert claims["ok_interp"] not in repair_wire
        repaired = result.value.model_dump()
        assert repaired["summary"] == initial["summary"]
        assert repaired["observations"][0] == initial["observations"][0]  # type: ignore[index]
        assert repaired["observations"][1] == {
            "text": claims["ok_ratio"],
            "evidence": ["ev_extra"],
        }
        assert len(repaired["observations"]) == 2
        assert repaired["interpretations"] == initial["interpretations"]
        assert repaired["controls"] == initial["controls"]
        assert repaired["limitations"] == initial["limitations"]
        assert repaired["open_questions"] == initial["open_questions"]
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_multiple_errors_on_one_claim_group_into_one_target_and_preserve_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.extract = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    scope, claims = _scope(pid)
    source_schema = evidence_schema(schemas.SourceFindings, set(scope.evidence))
    candidate = _candidate(claims)
    candidate["observations"] = [
        {"text": claims["ok_rows"], "evidence": ["ev_ok"]},
        {"text": "RMSD 888 nm", "evidence": ["ev_ok"]},
    ]
    first = ValidationError("unknown_evidence", ("observations", 1, "evidence", 0))
    second = ValidationError("unsupported_number", ("observations", 1, "text"))
    third = ValidationError("unsupported_number", ("interpretations", 0, "text"))
    fourth = ValidationError("unsupported_number", ("summary", "text"))
    first.related = (second, third, fourth)

    plan = plan_source_repair(candidate, first, source_schema)
    assert plan is not None
    assert len(plan.targets) == 3
    by_field = {target.field: target for target in plan.targets.values()}
    assert set(by_field) == {"observations.1", "interpretations.0", "summary"}
    assert len(by_field["observations.1"].issues) == 2
    assert by_field["interpretations.0"].is_interpretation is True
    assert by_field["summary"].is_interpretation is False

    # Verify target IDs change when candidate content or target route changes.
    changed_candidate = deepcopy(candidate)
    changed_candidate["controls"][0]["text"] = "Control distinto."  # type: ignore[index]
    other_plan = plan_source_repair(changed_candidate, first, source_schema)
    assert other_plan is not None
    assert set(other_plan.targets) != set(plan.targets)
    only_obs0 = ValidationError("unsupported_number", ("observations", 0, "text"))
    obs0_plan = plan_source_repair(candidate, only_obs0, source_schema)
    assert obs0_plan is not None
    assert set(obs0_plan.targets) != set(plan.targets)

    # Verify schema enum constraints are inherited by SourceClaimRepair.
    enum_values: list[list[str]] = []

    def collect_enums(node: object) -> None:
        if isinstance(node, dict):
            for key, prop in node.get("properties", {}).items():
                if key == "evidence" and isinstance(prop, dict):
                    enum_values.append(prop["items"]["enum"])
            for child in node.values():
                collect_enums(child)
        elif isinstance(node, list):
            for child in node:
                collect_enums(child)

    collect_enums(plan.schema)
    assert enum_values and all(refs == ["ev_extra", "ev_ok"] for refs in enum_values)

    # Apply multi-target patch across summary, observations.1 and interpretations.0.
    patch = {
        by_field["summary"].id: {"text": claims["ok_rmsd"], "evidence": ["ev_ok"]},
        by_field["observations.1"].id: {"text": claims["ok_ratio"], "evidence": ["ev_extra"]},
        by_field["interpretations.0"].id: {
            "text": claims["ok_interp"],
            "evidence": ["ev_ok"],
            "confidence": "high",
        },
    }
    patched = plan.apply(patch)
    assert patched["observations"][0] == candidate["observations"][0]  # type: ignore[index]
    assert patched["observations"][1] == {"text": claims["ok_ratio"], "evidence": ["ev_extra"]}
    assert patched["interpretations"][0]["confidence"] == "high"
    assert len(patched["observations"]) == 2
    assert len(patched["interpretations"]) == 1
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize(
    "attack",
    [
        "foreign_id",
        "missing_id",
        "duplicate_id",
        "wrong_type_claim",
        "wrong_type_interp",
        "non_object",
        "full_source_findings",
    ],
)
def test_scoped_repair_rejects_out_of_scope_or_malformed_patches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.extract = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    scope, claims = _scope(pid)
    candidate = _candidate(claims)
    candidate["interpretations"] = [
        {"text": "Medida 777 nm", "evidence": ["ev_ok"], "confidence": "low"}
    ]
    source_schema = evidence_schema(schemas.SourceFindings, set(scope.evidence))
    err = ValidationError("unsupported_number", ("observations", 1, "text"))
    err.related = (ValidationError("unsupported_number", ("interpretations", 0, "text")),)
    plan = plan_source_repair(candidate, err, source_schema)
    assert plan is not None
    by_field = {t.field: t.id for t in plan.targets.values()}
    obs_id = by_field["observations.1"]
    int_id = by_field["interpretations.0"]
    valid_claim = {"text": claims["ok_rmsd"], "evidence": ["ev_ok"]}
    valid_interp = {"text": claims["ok_interp"], "evidence": ["ev_ok"], "confidence": "low"}

    if attack == "foreign_id":
        raw = json.dumps({obs_id: valid_claim, int_id: valid_interp, "claim_foreign": valid_claim})
    elif attack == "missing_id":
        raw = json.dumps({obs_id: valid_claim})
    elif attack == "duplicate_id":
        raw = (
            '{"'
            + obs_id
            + '": '
            + json.dumps(valid_claim)
            + ', "'
            + obs_id
            + '": '
            + json.dumps(valid_claim)
            + ', "'
            + int_id
            + '": '
            + json.dumps(valid_interp)
            + "}"
        )
    elif attack == "wrong_type_claim":
        raw = json.dumps({obs_id: {**valid_claim, "confidence": "high"}, int_id: valid_interp})
    elif attack == "wrong_type_interp":
        raw = json.dumps({obs_id: valid_claim, int_id: valid_claim})
    elif attack == "non_object":
        raw = json.dumps({obs_id: "solo texto", int_id: valid_interp})
    else:
        full = deepcopy(candidate)
        full["result_id"] = "res_other"
        raw = json.dumps(full)

    if attack == "duplicate_id":
        with pytest.raises(ClientError, match="invalid_json"):
            json_object(raw)
    with pytest.raises(ValueError):
        plan.apply(raw)

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        title = wire["response_format"]["json_schema"]["schema"]["title"]
        content = json.dumps(candidate) if title == "SourceFindings" else raw
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        result = router.generate(
            "extract",
            project_ids={pid},
            prompt_name="source",
            prompt_version="test",
            messages=[{"role": "user", "content": "source package"}],
            schema=source_schema,
            validate=_validate_source(scope),
        )
        assert result is None
        rows = db.execute("SELECT ok, error FROM llm_call ORDER BY id").fetchall()
        assert len(rows) == 2 and [row[0] for row in rows] == [0, 0]
        second_error = json.loads(rows[1][1])
        assert second_error["category"] == "validation"
        if attack == "duplicate_id":
            assert second_error["rule"] == "invalid_json" and second_error["field"] == "$"
        else:
            assert second_error["rule"].startswith("schema_")
            assert "foreign" not in repr(second_error) and "res_other" not in repr(second_error)
        assert not list((Path(config.paths.data_dir) / "nodes").rglob("*.json"))
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize(
    "bad_patch", ["invented_ref", "bad_number", "altered_unit", "added_annotation"]
)
def test_schema_valid_patch_with_invalid_evidence_or_number_stays_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_patch: str
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.extract = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    scope, claims = _scope(pid)
    candidate = _candidate(claims)
    source_schema = schemas.SourceFindings.model_json_schema()

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        schema_info = wire["response_format"]["json_schema"]["schema"]
        if schema_info["title"] == "SourceFindings":
            body: dict[str, object] = candidate
        else:
            tid = next(iter(schema_info["properties"]))
            if bad_patch == "invented_ref":
                patch = {"text": claims["ok_rmsd"], "evidence": ["ev_invented"]}
            elif bad_patch == "bad_number":
                patch = {"text": "RMSD 987654321 Å.", "evidence": ["ev_ok"]}
            elif bad_patch == "altered_unit":
                patch = {"text": "RMSD 1.4 nm.", "evidence": ["ev_ok"]}
            else:
                patch = {"text": "RMSD 1.4 Å (nuevo).", "evidence": ["ev_ok"]}
            body = {tid: patch}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        result = router.generate(
            "extract",
            project_ids={pid},
            prompt_name="source",
            prompt_version="test",
            messages=[{"role": "user", "content": "source package"}],
            schema=source_schema,
            validate=_validate_source(scope),
        )
        assert result is None
        assert router.issues[-1]["rule"] in {"unknown_evidence", "unsupported_number"}
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize(
    "case",
    ["invalid_json", "schema_extra", "global_result_id", "empty_path", "other_stage"],
)
def test_global_errors_schema_errors_and_other_stages_keep_full_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.extract = ["internal"]
    config.llm.routing.conceptual = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    scope, claims = _scope(pid)
    source_schema = evidence_schema(schemas.SourceFindings, set(scope.evidence))
    good_source = _candidate(claims)
    good_source["observations"] = [{"text": claims["ok_rows"], "evidence": ["ev_ok"]}]

    assert (
        plan_source_repair(
            good_source, ValidationError("unknown_result", ("result_id",)), source_schema
        )
        is None
    )
    assert (
        plan_source_repair(good_source, ValidationError("unknown_evidence", ()), source_schema)
        is None
    )

    schemas_seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        title = wire["response_format"]["json_schema"]["schema"]["title"]
        schemas_seen.append(title)
        if case == "other_stage":
            body: object = (
                {"unexpected": True}
                if len(schemas_seen) == 1
                else {
                    "highlights": [],
                    "review_candidate": None,
                }
            )
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(body)}}]}
            )
        if len(schemas_seen) == 1:
            if case == "invalid_json":
                content = "{broken"
            elif case == "schema_extra":
                bad = deepcopy(good_source)
                bad["extra_key"] = "unexpected"
                content = json.dumps(bad)
            elif case == "global_result_id":
                bad = deepcopy(good_source)
                bad["result_id"] = "res_other"
                content = json.dumps(bad)
            else:
                bad = deepcopy(good_source)
                bad["observations"] = [{"text": claims["ok_rows"], "evidence": ["ev_ok"]}]
                content = json.dumps(bad)
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(good_source)}}]}
        )

    def validate_empty(value: dict[str, object]) -> schemas.SourceFindings:
        parsed = _validate_source(scope)(value)
        if case == "empty_path" and len(schemas_seen) == 1:
            raise ValidationError("unknown_evidence", ())
        return parsed

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        if case == "other_stage":
            res = router.generate(
                "conceptual",
                project_ids={pid},
                prompt_name="conceptual",
                prompt_version="test",
                messages=[{"role": "user", "content": "overview"}],
                schema=schemas.DailyOverview.model_json_schema(),
                validate=lambda v: schemas.DailyOverview.model_validate(v),
            )
            assert res is not None and schemas_seen == ["DailyOverview", "DailyOverview"]
        else:
            res = router.generate(
                "extract",
                project_ids={pid},
                prompt_name="source",
                prompt_version="test",
                messages=[{"role": "user", "content": "source package"}],
                schema=source_schema,
                validate=validate_empty,
            )
            assert res is not None and schemas_seen == ["SourceFindings", "SourceFindings"]
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize("grounding_approved", [False, True])
def test_scoped_repair_respects_grounding_audit_and_caches_full_source_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, grounding_approved: bool
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    config.projects[0].external_allowed = False
    config.llm.routing.extract = ["nan", "internal"]
    config.llm.routing.contrast = ["nan", "internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    now = datetime(2026, 11, 4, 19, tzinfo=UTC).isoformat()
    report = Report(
        "rep_scoped",
        "daily",
        now,
        now,
        now,
        evidence=[
            EvidenceEntry(
                "ev_s1",
                pid,
                "doc_change",
                "docs/note.md",
                "RMSD 1.4 Å en control pendiente.",
                now,
                None,
                "observed",
                {"path": "docs/note.md", "capture_origin": "observed_change"},
            )
        ],
        results=[ResultEntry("res_s1", pid, "Ensayo", None, "pending", ["ev_s1"])],
    )
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        requests.append(wire)
        title = wire["response_format"]["json_schema"]["schema"]["title"]
        if title == "SourceFindings":
            body: dict[str, object] = {
                "result_id": "res_s1",
                "summary": {"text": "RMSD 1.4 Å.", "evidence": ["ev_s1"]},
                "observations": [
                    {"text": "Control pendiente.", "evidence": ["ev_s1"]},
                    {"text": "Medida 999 nm.", "evidence": ["ev_s1"]},
                ],
                "interpretations": [],
                "controls": [],
                "limitations": [],
                "open_questions": [],
            }
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(body)}}]}
            )
        if title == "SourceClaimRepair":
            tid = next(iter(wire["response_format"]["json_schema"]["schema"]["properties"]))
            body = {tid: {"text": "RMSD 1.4 Å.", "evidence": ["ev_s1"]}}
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(body)}}]}
            )
        if title == "GroundingAudit" and not grounding_approved:
            audit = {
                "approved": False,
                "issues": [
                    {
                        "rule": "unsupported_claim",
                        "field": ["observations", 1, "text"],
                        "evidence": ["ev_s1"],
                        "source_quote": "RMSD 1.4 Å en control pendiente.",
                    }
                ],
            }
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(audit)}}]}
            )
        return fake_response(request)

    with closing(connect(tmp_path / "db.sqlite")) as db:
        first_report = deepcopy(report)
        enrich(
            db,
            config,
            first_report,
            Router(db, config, client=Client(transport=httpx.MockTransport(respond))),
        )
        validate_report(first_report, {"ev_s1"})
        assert all(w["model"] == config.llm.providers["internal"].model for w in requests)
        titles = [w["response_format"]["json_schema"]["schema"]["title"] for w in requests]
        assert "SourceClaimRepair" in titles
        if not grounding_approved:
            assert "extract:res_s1" not in first_report.sections
            assert "extract:res_s1" in first_report.pending
            with pytest.raises(ValueError):
                require_complete(first_report)
            return

        require_complete(first_report)
        key = first_report.source_units["res_s1"][0]
        assert first_report.sections[key]["observations"][0]["text"] == "Control pendiente."
        assert first_report.sections[key]["observations"][1]["text"] == "RMSD 1.4 Å."

        # Verify persisted cache node holds full SourceFindings and is reused without HTTP calls.
        node_files = list((Path(config.paths.data_dir) / "nodes").rglob("*.json"))
        source_nodes = [
            json.loads(p.read_text())
            for p in node_files
            if json.loads(p.read_text()).get("key") == first_report.model_info[key]["cache_key"]
        ]
        assert len(source_nodes) == 1
        schemas.SourceFindings.model_validate(source_nodes[0]["value"])
        count = len(requests)
        second_report = deepcopy(report)
        enrich(
            db,
            config,
            second_report,
            Router(db, config, client=Client(transport=httpx.MockTransport(respond))),
        )
        require_complete(second_report)
        assert len(requests) == count
        assert second_report.model_info[key]["reused"] == "true"
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_scoped_repair_enforces_budget_secrets_and_html_sanitization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    config.projects[0].external_allowed = True
    secret = "PRIVATE_SCOPED_SECRET_9911"
    config.email.password_env = "DIGEST_PRIVATE_SCOPED_PASS"
    monkeypatch.setenv(config.email.password_env, secret)
    for provider in config.llm.providers.values():
        monkeypatch.setenv(provider.api_key_env, "synthetic-key")
    pid = config.projects[0].id
    scope, claims = _scope(pid)
    source_schema = evidence_schema(schemas.SourceFindings, set(scope.evidence))
    initial = {
        "result_id": "res_test",
        "summary": {"text": claims["ok_rmsd"], "evidence": ["ev_ok"]},
        "observations": [
            {"text": "Medida 999 nm con " + secret, "evidence": ["ev_ok"]},
            {"text": "<script>PRIVATE_HTML</script>", "evidence": ["ev_ok"]},
        ],
        "interpretations": [],
        "controls": [{"text": "Control estable sin cambios.", "evidence": ["ev_ok"]}],
        "limitations": [],
        "open_questions": [],
    }
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        requests.append(wire)
        schema_info = wire["response_format"]["json_schema"]["schema"]
        if schema_info["title"] == "SourceFindings":
            body: dict[str, object] = initial
        else:
            body = {
                tid: {"text": claims["ok_rows"], "evidence": ["ev_ok"]}
                for tid in schema_info["properties"]
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

    base_messages = [{"role": "user", "content": "package without secret"}]
    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        res = router.generate(
            "extract",
            project_ids={pid},
            prompt_name="source",
            prompt_version="budget",
            messages=base_messages,
            schema=source_schema,
            validate=_validate_source(scope),
            max_message_chars=50_000,
        )
        assert res is not None and len(requests) == 2
        repair_wire = json.dumps(requests[1]["messages"], ensure_ascii=False)
        assert secret not in repair_wire
        assert "PRIVATE_HTML" not in repair_wire
        assert "Control estable sin cambios." not in repair_wire
        assert "[redactado]" in repair_wire
        node_text = "\n".join(
            p.read_text() for p in (Path(config.paths.data_dir) / "nodes").rglob("*.json")
        )
        assert secret not in node_text and "PRIVATE_HTML" not in node_text

        # Now test exact budget overflow on scoped repair falling back to next provider.
        requests.clear()
        tight_limit = len(json.dumps(base_messages, ensure_ascii=False)) + 10
        router_budget = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        res2 = router_budget.generate(
            "extract",
            project_ids={pid},
            prompt_name="source",
            prompt_version="tight",
            messages=base_messages,
            schema=source_schema,
            validate=_validate_source(scope),
            max_message_chars=tight_limit,
        )
        assert res2 is None
        assert len(requests) == 2
        assert all(w["messages"] == base_messages for w in requests)
        assert sum(i["rule"] == "repair_message_budget_exceeded" for i in router_budget.issues) == 2
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_scoped_repair_blanks_all_html_and_checks_schema_and_evidence_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    scope, claims = _scope(pid)
    source_schema = evidence_schema(schemas.SourceFindings, set(scope.evidence))
    check_source = _validate_source(scope)

    # Case 1: unknown_evidence + HTML in the same claim's text.
    cand1 = _candidate(claims)
    cand1["observations"] = [{"text": "<script>HTML_CASE_1</script>", "evidence": ["ev_invented"]}]
    with pytest.raises(ValidationError) as exc1:
        check_source(cand1)
    plan1 = plan_source_repair(cand1, exc1.value, source_schema)
    assert plan1 is not None and "HTML_CASE_1" not in json.dumps(plan1.messages)

    # Case 2: >20 prior validation failures + HTML in claim 21+.
    cand2 = _candidate(claims)
    cand2["observations"] = [{"text": "Medida 999 nm.", "evidence": ["ev_ok"]} for _ in range(21)]
    cand2["observations"].append({"text": "<script>HTML_CASE_2</script>", "evidence": ["ev_ok"]})  # type: ignore[attr-defined]
    with pytest.raises(ValidationError) as exc2:
        check_source(cand2)
    plan2 = plan_source_repair(cand2, exc2.value, source_schema)
    assert plan2 is not None and "HTML_CASE_2" not in json.dumps(plan2.messages)

    # Case 3: HTML inside evidence list or result_id.
    cand3 = _candidate(claims)
    cand3["result_id"] = "<script>HTML_RESULT_ID</script>"
    cand3["observations"] = [
        {"text": claims["ok_rows"], "evidence": ["<script>HTML_EVIDENCE</script>"]}
    ]
    with pytest.raises(ValidationError) as exc3:
        check_source(cand3)
    plan3 = plan_source_repair(cand3, exc3.value, source_schema)
    assert plan3 is not None
    wire3 = json.dumps(plan3.messages)
    assert "HTML_RESULT_ID" not in wire3 and "HTML_EVIDENCE" not in wire3

    # Reject nested duplicate keys and NaN in raw patch; check schema limit and evidence bounds.
    valid_plan = plan_source_repair(
        _candidate(claims),
        ValidationError("unsupported_number", ("observations", 1, "text")),
        source_schema,
    )
    assert valid_plan is not None
    tid = next(iter(valid_plan.targets))
    nested_dup = '{"' + tid + '": {"text": "A", "text": "B", "evidence": ["ev_ok"]}}'
    with pytest.raises(ClientError, match="invalid_json"):
        valid_plan.apply(nested_dup)
    with pytest.raises(ValueError):
        valid_plan.apply('{"' + tid + '": {"text": NaN, "evidence": ["ev_ok"]}}')
    assert (
        plan_source_repair(
            _candidate(claims),
            ValidationError("unsupported_number", ("observations", 1, "text")),
            source_schema,
            max_schema_chars=100,
        )
        is None
    )
    assert (
        plan_source_repair(
            _candidate(claims),
            ValidationError("unknown_evidence", ("observations", 0, "evidence", 5)),
            source_schema,
        )
        is None
    )
    assert (
        plan_source_repair(
            _candidate(claims),
            ValidationError("unknown_evidence", ("summary", "evidence", -1)),
            source_schema,
        )
        is None
    )

    # Verify fake_response supports SourceClaimRepair schemas (including Interpretation).
    err_both = ValidationError("unknown_evidence", ("observations", 1, "evidence"))
    err_both.related = (ValidationError("unknown_evidence", ("interpretations", 0, "evidence")),)
    both_plan = plan_source_repair(_candidate(claims), err_both, source_schema)
    assert both_plan is not None
    fake_req = httpx.Request(
        "POST",
        "http://example.invalid/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": "sys"},
                {
                    "role": "user",
                    "content": '<context>{"result_id":"res_test"}</context>'
                    '<evidence id="ev_ok">{"id":"ev_ok","excerpt":"RMSD 1.4 Å"}</evidence>',
                },
            ],
            "response_format": {"type": "json_schema", "json_schema": {"schema": both_plan.schema}},
        },
    )
    fake_patch = json.loads(fake_response(fake_req).json()["choices"][0]["message"]["content"])
    rebuilt = both_plan.apply(fake_patch)
    assert schemas.SourceFindings.model_validate(rebuilt)
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_scoped_repair_rejects_dropping_source_numbers_and_preserves_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.llm.routing.extract = ["internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    pid = config.projects[0].id
    entries = {
        "ev_tbl": EvidenceEntry(
            "ev_tbl",
            pid,
            "diff",
            "PENDIENTES.md",
            "Tabla: rf3 33 (las 29 de rfaa + 9BSH_A) y 4 secuencias BAD (9BSH_A 257 vs 280).",
            "2026-11-04T19:00:00+00:00",
            None,
            "observed",
            {"path": "PENDIENTES.md", "capture_origin": "observed_change"},
        )
    }
    scope = EvidencePackage(entries, {pid}, {"res_test"})
    source_schema = evidence_schema(schemas.SourceFindings, set(scope.evidence))
    package_dict = {
        "evidence": [{"id": "ev_tbl", "kind": "diff", "excerpt": entries["ev_tbl"].excerpt}]
    }
    candidate = {
        "result_id": "res_test",
        "summary": {"text": "Tabla de pendientes registrada.", "evidence": ["ev_tbl"]},
        "observations": [
            {"text": "Tabla: rf3 33 y 4 predicciones BAD (257 vs 280).", "evidence": ["ev_tbl"]}
        ],
        "interpretations": [],
        "controls": [],
        "limitations": [],
        "open_questions": [],
    }
    with pytest.raises(ValidationError) as exc_info:
        _validate_source(scope)(candidate)
    plan = plan_source_repair(candidate, exc_info.value, source_schema, package=package_dict)
    assert plan is not None
    tid = next(iter(plan.targets))
    target = plan.targets[tid]
    assert target.requires_quantity is True
    assert set(target.required_values) == {33.0, 4.0, 257.0, 280.0}
    assert "preserve_numbers" in plan.messages[-1]["content"]

    # Dropping all numbers or a subset of source-backed numbers must fail deterministically.
    with pytest.raises(ValidationError, match="unsupported_number"):
        plan.apply({tid: {"text": "Tabla con faltantes y BAD sin cifras.", "evidence": ["ev_tbl"]}})
    with pytest.raises(ValidationError, match="unsupported_number"):
        plan.apply(
            {
                tid: {
                    "text": "Tabla con 4 secuencias BAD (257 vs 280).",
                    "evidence": ["ev_tbl"],
                }
            }
        )

    # Retaining all source-backed numbers with corrected label and parenthetical passes.
    rebuilt = plan.apply(
        {
            tid: {
                "text": (
                    "Tabla: rf3 33 (las 29 de rfaa + 9BSH_A) y 4 secuencias BAD (257 vs 280)."
                ),
                "evidence": ["ev_tbl"],
            }
        }
    )
    assert _validate_source(scope)(rebuilt)

    # When a claim cites text-only evidence or hallucinates a number that appears only in an
    # uncited evidence entry, repairing it back to truthful prose or its cited value must succeed,
    # while metric stats/change numbers cited by the claim remain protected.
    mixed_entries = {
        "ev_txt": EvidenceEntry(
            "ev_txt",
            pid,
            "doc_change",
            "NOTES.md",
            "Control pendiente desde 2026-11-04T19:00:00+00:00 (commit 1234abcd, SRR12345_1).",
            "2026-11-04T19:00:00+00:00",
            None,
            "observed",
            {"path": "NOTES.md", "capture_origin": "observed_change"},
        ),
        "ev_num": EvidenceEntry(
            "ev_num",
            pid,
            "metric",
            "scores.csv",
            "RMSD 1.4 Å.",
            "2026-11-04T19:00:00+00:00",
            None,
            "observed",
            {
                "path": "scores.csv",
                "capture_origin": "observed_change",
                "stats": {"rmsd": {"mean": 1.4, "n": 20, "flag": True, "bad": float("nan")}},
                "change": {"rmsd": {"delta": -0.2}},
            },
        ),
        "ev_other": EvidenceEntry(
            "ev_other",
            pid,
            "doc_change",
            "OTHER.md",
            "4 lotes adicionales.",
            "2026-11-04T19:00:00+00:00",
            None,
            "observed",
            {"path": "OTHER.md", "capture_origin": "observed_change"},
        ),
    }
    mixed_scope = EvidencePackage(mixed_entries, {pid}, {"res_test"})
    mixed_schema = evidence_schema(schemas.SourceFindings, set(mixed_scope.evidence))
    mixed_pkg = {
        "evidence": [
            {"id": "ev_txt", "kind": "doc_change", "excerpt": mixed_entries["ev_txt"].excerpt},
            {
                "id": "ev_num",
                "kind": "metric",
                "excerpt": mixed_entries["ev_num"].excerpt,
                "meta": mixed_entries["ev_num"].meta,
            },
            {"id": "ev_other", "kind": "doc_change", "excerpt": mixed_entries["ev_other"].excerpt},
        ]
    }
    hallucinated = {
        "result_id": "res_test",
        "summary": {"text": "RMSD 1.4 Å.", "evidence": ["ev_num"]},
        "observations": [
            {
                "text": "Se ejecutaron 4 réplicas tras 19:00:00 del 2026-11-04 (SRR12345_1).",
                "evidence": ["ev_txt"],
            },
            {"text": "RMSD 4 Å.", "evidence": ["ev_num"]},
            {"text": "Media 1.4 nm y delta -0.2.", "evidence": ["ev_num"]},
        ],
        "interpretations": [],
        "controls": [],
        "limitations": [],
        "open_questions": [],
    }
    with pytest.raises(ValidationError) as mixed_exc:
        _validate_source(mixed_scope)(hallucinated)
    mixed_plan = plan_source_repair(hallucinated, mixed_exc.value, mixed_schema, package=mixed_pkg)
    assert mixed_plan is not None
    by_field = {t.field: t for t in mixed_plan.targets.values()}
    assert by_field["observations.0"].required_values == ()
    assert by_field["observations.0"].requires_quantity is False
    assert by_field["observations.1"].required_values == ()
    assert by_field["observations.1"].requires_quantity is False
    assert by_field["observations.2"].required_values == (1.4, -0.2)
    assert by_field["observations.2"].requires_quantity is True

    # Dropping delta -0.2 from the metric claim fails deterministically.
    with pytest.raises(ValidationError, match="unsupported_number"):
        mixed_plan.apply(
            {
                by_field["observations.0"].id: {
                    "text": "Control pendiente desde 2026-11-04T19:00:00+00:00.",
                    "evidence": ["ev_txt"],
                },
                by_field["observations.1"].id: {"text": "RMSD 1.4 Å.", "evidence": ["ev_num"]},
                by_field["observations.2"].id: {"text": "Media 1.4.", "evidence": ["ev_num"]},
            }
        )

    # Faithful repair of all three mixed claims passes.
    rebuilt_mixed = mixed_plan.apply(
        {
            by_field["observations.0"].id: {
                "text": "Control pendiente desde 2026-11-04T19:00:00+00:00.",
                "evidence": ["ev_txt"],
            },
            by_field["observations.1"].id: {"text": "RMSD 1.4 Å.", "evidence": ["ev_num"]},
            by_field["observations.2"].id: {
                "text": "Media 1.4 y delta -0.2.",
                "evidence": ["ev_num"],
            },
        }
    )
    assert _validate_source(mixed_scope)(rebuilt_mixed)

    # Verify Router.generate(..., package=...) blocks evasion without leaking values or caching.
    def respond_evasion(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        schema_info = wire["response_format"]["json_schema"]["schema"]
        if schema_info["title"] == "SourceFindings":
            body: dict[str, object] = candidate
        else:
            tid_r = next(iter(schema_info["properties"]))
            body = {tid_r: {"text": "Tabla sin cifras en 2026-11-04.", "evidence": ["ev_tbl"]}}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

    with closing(connect(tmp_path / "router_b1.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond_evasion)))
        res = router.generate(
            "extract",
            project_ids={pid},
            prompt_name="source",
            prompt_version="test",
            messages=[{"role": "user", "content": "source package"}],
            schema=source_schema,
            validate=_validate_source(scope),
            section="extract:res_test",
            package=package_dict,
        )
        assert res is None
        rows = db.execute("SELECT ok, error FROM llm_call ORDER BY id").fetchall()
        assert [row[0] for row in rows] == [0, 0]
        err2 = json.loads(rows[1][1])
        assert err2 == {
            "stage": "extract",
            "section": "extract:res_test",
            "category": "validation",
            "rule": "unsupported_number",
            "field": "observations.0.text",
        }
        assert not list((Path(config.paths.data_dir) / "nodes").rglob("*.json"))
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
