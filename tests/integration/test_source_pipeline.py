"""Bounded source generation with full lineage, controls and privacy."""

import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from digest.config import load_config
from digest.db import connect
from digest.llm.client import Client
from digest.llm.router import Router
from digest.llm.validator import ValidationError, validate_report
from digest.report.builder import enrich
from digest.report.completeness import require_complete
from digest.report.model import EvidenceEntry, Report, ResultEntry
from digest.report.packets import SOURCE_PACKET_CHARS
from tests.fixtures.llm import fake_response
from tests.fixtures.make_projects import build_projects


@pytest.mark.parametrize("invalid", [None, "number", "reference"])
def test_large_result_splits_into_small_validated_packets_without_losing_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str | None
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    project = config.projects[0]
    project.external_allowed = False
    config.llm.routing.extract = ["nan", "internal"]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    now = datetime(2026, 11, 4, 19, tzinfo=UTC).isoformat()
    report = Report("rep_test", "daily", now, now, now)
    report.evidence = [
        EvidenceEntry(
            f"ev_document_{n}",
            project.id,
            "doc_change",
            f"docs/part-{n}.md",
            "Observación con control pendiente. " * 30,
            now,
            None,
            "observed",
            {"path": f"docs/part-{n}.md", "capture_origin": "initial_inventory"},
        )
        for n in range(30)
    ]
    report.results = [
        ResultEntry(
            "res_test",
            project.id,
            "Resultado con fuentes extensas",
            "AN-01",
            "closed_by_human",
            [e.id for e in report.evidence],
        )
    ]
    requests = []
    bad_reference = None

    def respond(request):
        nonlocal bad_reference
        wire = json.loads(request.content)
        title = wire["response_format"]["json_schema"]["schema"]["title"]
        requests.append(wire)
        response = fake_response(request)
        value = json.loads(response.json()["choices"][0]["message"]["content"])
        if title == "SourceFindings":
            if bad_reference is None:
                bad_reference = value["observations"][0]["evidence"][0]
            if value["observations"][0]["evidence"][0] == bad_reference:
                if invalid == "number":
                    value["observations"][0]["text"] = "Efecto 987654321 Å"
                elif invalid == "reference":
                    value["observations"][0]["evidence"] = ["ev_invented"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    with closing(connect(tmp_path / "db")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        enrich(db, config, report, router)
        validate_report(report, {e.id for e in report.evidence})
    keys = report.source_units["res_test"]
    assert 1 < len(keys) < len(report.evidence)
    assert report.results[0].review_state == "closed_by_human"
    assert len(report.results) == 1 and len(report.evidence) == 30
    source_calls = [
        w
        for w in requests
        if w["response_format"]["json_schema"]["schema"]["title"] == "SourceFindings"
    ]
    assert all(
        len(json.dumps(w["messages"], ensure_ascii=False)) <= SOURCE_PACKET_CHARS
        for w in source_calls
    )
    assert all(w["model"] == config.llm.providers["internal"].model for w in requests)
    if invalid:
        assert "extract:res_test" in report.pending
        assert "extract:res_test" not in report.sections
        assert report.sections, "Successful independent source pieces remain available"
        assert all(
            w["response_format"]["json_schema"]["schema"]["title"] == "SourceFindings"
            for w in requests
        )
        with pytest.raises(ValueError):
            require_complete(report)
    else:
        require_complete(report)
        assert {e["id"] for key in keys for e in report.packages[key]["evidence"]} == {
            e.id for e in report.evidence
        }
        assert all(len(report.packages[key]["evidence"]) > 1 for key in keys)
        assert len(report.observations) == 30
        assert all(o["origin"] == "initial_inventory" for o in report.observations.values())
        report.observations[report.evidence[0].id]["computed"] = [{"value": 123}]
        with pytest.raises(ValidationError, match="observation modified"):
            validate_report(report, {e.id for e in report.evidence})
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_oversized_comparison_is_pending_and_never_sent_as_a_truncated_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    config.limits.max_project_package_chars = 6000
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    now = "2026-11-04T19:00:00+00:00"
    project = config.projects[0].id
    evidence = [
        EvidenceEntry(
            "ev_control",
            project,
            "metric",
            "experiment/control.csv",
            "Control " * 300,
            now,
            None,
            "observed",
            {"path": "experiment/control.csv"},
        ),
        EvidenceEntry(
            "ev_sample",
            project,
            "metric",
            "experiment/sample.csv",
            "Muestra " * 300,
            now,
            None,
            "observed",
            {"path": "experiment/sample.csv"},
        ),
    ]
    report = Report(
        "rep_large_comparison",
        "daily",
        now,
        now,
        now,
        evidence=evidence,
        results=[
            ResultEntry(
                "res_comparison", project, "Comparación", None, "pending", [e.id for e in evidence]
            )
        ],
    )
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
    assert not requests
    assert {e.id for e in report.evidence} == {"ev_sample", "ev_control"}
    assert "extract:res_comparison" in report.pending
    assert any(
        issue["rule"] == "coherent_unit_budget_exceeded"
        for issues in report.pending.values()
        for issue in issues
    )
    assert not report.sections and not report.packages
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_one_changed_result_invalidates_only_its_sources_and_descendants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from copy import deepcopy

    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    project = config.projects[0].id
    now = "2026-11-04T19:00:00+00:00"
    inventory = Report("rep_branches", "daily", now, now, now)
    for n in range(3):
        e = EvidenceEntry(
            f"ev_{n}",
            project,
            "doc_change",
            f"experiment-{n}/summary.md",
            "Control observado",
            now,
            None,
            "observed",
            {"path": f"experiment-{n}/summary.md"},
            str(n) * 64,
        )
        inventory.evidence.append(e)
        inventory.results.append(
            ResultEntry(f"res_{n}", project, "Contraste", None, "pending", [e.id])
        )
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return fake_response(request)

    client = Client(transport=httpx.MockTransport(respond))
    with closing(connect(tmp_path / "db")) as db:
        first = enrich(db, config, deepcopy(inventory), Router(db, config, client=client))
        count = len(calls)
        assert count == 5
        repeated = enrich(db, config, deepcopy(inventory), Router(db, config, client=client))
        assert len(calls) == count
        assert all(
            m.get("reused") == "true"
            for k, m in repeated.model_info.items()
            if not k.startswith("extract:")
        )
        changed = deepcopy(inventory)
        changed.evidence[0].id = "ev_changed"
        changed.evidence[0].content_hash = "f" * 64
        changed.evidence[0].excerpt = "Se observó un control adicional"
        changed.results[0].evidence = ["ev_changed"]
        updated = enrich(db, config, changed, Router(db, config, client=client))
        assert len(calls) == count + 3
        for result in ("res_1", "res_2"):
            key = updated.source_units[result][0]
            assert updated.model_info[key]["reused"] == "true"
            assert updated.sections[key] == first.sections[key]
        assert updated.model_info["conceptual"]["reused"] == "false"
        assert updated.model_info["plan"]["reused"] == "false"
        validate_report(updated, {e.id for e in updated.evidence})
        require_complete(updated)
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
