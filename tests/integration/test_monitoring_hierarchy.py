"""The full model/validation path monitors a large historical inventory."""

import copy
import json
from dataclasses import asdict

import pytest

from digest import queue, watchlist
from digest.llm.router import Router
from digest.llm.validator import validate_report
from digest.report.builder import enrich
from digest.report.completeness import missing_sections, require_complete
from digest.report.model import Coverage, EvidenceEntry, Report, ResultEntry
from tests.integration.test_publication import config as config


def inventory(config, db, count=2600):
    pid = config.projects[0].id
    watchlist.save(
        db,
        config,
        watchlist.draft("Semillas por modelo", [pid], 50),
        watchlist.expected(db),
        "a" * 32,
    )
    start, end = "2026-11-16T00:00:00+00:00", "2026-11-16T12:00:00+00:00"
    previous = "2026-11-09T12:00:00+00:00"
    report = Report(
        "large_initial",
        "preview",
        start,
        end,
        end,
        coverage=[Coverage(1, pid, "structures", "ok", [])],
        watchlist=watchlist.freeze(db, config),
    )
    for i in range(count):
        path = "structures/protein_" + str(i) + "/model.pdb"
        report.evidence.append(
            EvidenceEntry(
                "ev_large_" + str(i),
                pid,
                "structure",
                path,
                "Metadatos de estructura almacenada. " + "x" * 650,
                end,
                previous,
                "event",
                {"path": path, "capture_origin": "initial_inventory"},
            )
        )
    report.results = [
        ResultEntry(
            "result", pid, "Referencia inicial", None, "pending", [e.id for e in report.evidence]
        )
    ]
    return report


def test_full_large_monitoring_generation_keeps_inventory_and_validates_parent_audits(config):
    with queue.writing(config) as db:
        report = inventory(config, db)
        original = [asdict(e) for e in report.evidence]
        enrich(db, config, report, Router(db, config))
        assert not report.pending
        require_complete(report)
        validate_report(report, {e.id for e in report.evidence})
        assert len(report.evidence) == 2600
        assert all(r.reference_only for r in report.results)
        assert [asdict(e) for e in report.evidence] == original
        root = "watch:" + report.watchlist["items"][0]["id"]
        assert root in report.sections and report.sections[root]["current_evidence"] == []
        assert report.packages[root]["context"]["derived_monitoring"] is True
        assert all(len(json.dumps(p["context"])) < 64000 for p in report.packages.values())
        for key, package in report.packages.items():
            if key.startswith("watchctx:"):
                assert "check:" + key in report.sections
                assert all(p in report.sections for p in package["parents"])


def test_leaf_failure_blocks_assessment_and_valid_nodes_are_reused_on_retry(config, monkeypatch):
    original_generate = Router.generate
    failed = False

    def fail_one(self, task, **kwargs):
        nonlocal failed
        section = kwargs.get("section", "")
        if section.startswith("watchctx:") and ":source:" in section and not failed:
            failed = True
            return None
        return original_generate(self, task, **kwargs)

    with queue.writing(config) as db:
        report = inventory(config, db, count=150)
        frozen = copy.deepcopy(report)
        monkeypatch.setattr(Router, "generate", fail_one)
        enrich(db, config, report, Router(db, config))
        assert failed and report.pending
        assert not any(k.startswith("watch:") for k in report.sections)
        validate_report(report, {e.id for e in report.evidence})
        before = db.execute("SELECT count(*) FROM llm_call").fetchone()[0]
        monkeypatch.setattr(Router, "generate", original_generate)
        enrich(db, config, frozen, Router(db, config))
        require_complete(frozen)
        validate_report(frozen, {e.id for e in frozen.evidence})
        assert any(v.get("reused") == "true" for v in frozen.model_info.values())
        assert db.execute("SELECT count(*) FROM llm_call").fetchone()[0] > before


def test_missing_child_or_changed_parent_cannot_pass_final_publication(config):
    with queue.writing(config) as db:
        report = inventory(config, db, count=100)
        enrich(db, config, report, Router(db, config))
    root = "watch:" + report.watchlist["items"][0]["id"]
    assert root in report.sections
    altered = copy.deepcopy(report)
    child = next(k for k in altered.sections if k.startswith("watchctx:"))
    altered.sections.pop(child)
    altered.packages.pop(child)
    assert child in missing_sections(altered)
    with pytest.raises(ValueError):
        require_complete(altered)
    with pytest.raises(ValueError):
        validate_report(altered, {e.id for e in altered.evidence})
    altered = copy.deepcopy(report)
    child = next(iter(altered.packages[root]["context"]["parent_pieces"]))
    altered.packages[root]["context"]["parent_pieces"][child]["limits"] = []
    with pytest.raises(ValueError):
        validate_report(altered, {e.id for e in altered.evidence})


def test_partial_capture_with_no_activity_remains_pending_after_hierarchical_monitoring(config):
    with queue.writing(config) as db:
        report = inventory(config, db, count=100)
        report.coverage[0].status = "partial"
        report.coverage[0].omitted = [{"locator": "project", "reason": "scan_limit"}]
        enrich(db, config, report, Router(db, config))
    assert any(key.startswith("watch:") for key in report.sections)
    assert "capture" in missing_sections(report)
    with pytest.raises(ValueError):
        require_complete(report)
