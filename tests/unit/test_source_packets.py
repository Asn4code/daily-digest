"""Keep comparisons coherent, source facts exact, and packet planning deterministic."""

import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from digest.collectors.base import CaptureContext, CollectorOutput, EvidenceDraft
from digest.collectors.store import persist
from digest.config import ProjectConfig
from digest.db import connect
from digest.llm.schemas import Number
from digest.llm.validator import EvidencePackage, ValidationError, validate
from digest.report.model import EvidenceEntry
from digest.report.observations import normalize
from digest.report.packets import plan, units


def entry(
    ident: str, kind: str, path: str | None, text: str = "Control observado"
) -> EvidenceEntry:
    return EvidenceEntry(
        ident,
        "p",
        kind,
        path or ident,
        text,
        "2026-11-04T19:00:00+00:00",
        None,
        "observed",
        {"path": path} if path else {},
    )


def test_comparison_control_and_note_stay_together_across_directories() -> None:
    entries = [
        entry("sample", "metric", "mutant/score.csv"),
        entry("control", "metric", "reference/control.csv"),
        entry("note", "task_note", None, "Comparar mutant/score.csv con reference/control.csv."),
        entry("other", "doc_change", "methods/other.md"),
    ]
    coherent, anchors = units(entries)
    assert not anchors
    assert sorted(["sample", "control", "note"]) in coherent
    packets = plan(entries, size=lambda ids: len(ids) * 100, limit=250)
    comparison = next(p for p in packets if "sample" in p.evidence)
    assert set(comparison.evidence) == {"sample", "control", "note"}
    assert not comparison.fits
    assert any(p.fits and p.evidence == ["other"] for p in packets)


def test_many_independent_documents_are_batched_not_one_call_per_file() -> None:
    entries = [entry(f"ev_{n}", "doc_change", f"docs/section-{n}.md") for n in range(30)]

    def size(ids):
        return len(ids) * 100

    packets = plan(entries, size=size, limit=600)
    assert len(packets) == 5
    assert all(p.fits and len(p.evidence) == 6 for p in packets)
    assert {eid for p in packets for eid in p.evidence} == {e.id for e in entries}
    assert plan(list(reversed(entries)), size=size, limit=600) == packets


def test_notebook_cells_and_comparison_artifacts_share_one_unit() -> None:
    entries = [
        entry("cell_a", "notebook_change", "analysis/compare.ipynb"),
        entry("cell_b", "notebook_change", "analysis/compare.ipynb"),
        entry("figure", "figure", "analysis/comparison.png"),
        entry("data", "metric", "analysis/control.csv"),
    ]
    coherent, anchors = units(entries)
    assert len(coherent) == 1 and not anchors
    packets = plan(entries, size=lambda ids: len(ids), limit=3)
    assert len(packets) == 1 and not packets[0].fits
    assert set(packets[0].evidence) == {e.id for e in entries}


def test_metric_facts_keep_exact_statistics_and_deltas_without_invented_units() -> None:
    e = entry("ev", "metric", "scores.csv")
    e.meta.update(stats={"score": {"n": 2, "mean": -1.25}}, change={"score": {"mean": -0.25}})
    facts = normalize(e)
    assert facts["scientific_status"] == "source_observation"
    assert {f["value"] for f in facts["computed"]} == {2, -1.25, -0.25}
    assert all(f["unit"] is None for f in facts["computed"])
    scope = EvidencePackage({e.id: e}, {"p"})
    validate(Number(name="Delta", value=-0.25, unit=None, evidence=e.id), scope)
    with pytest.raises(ValidationError):
        validate(Number(name="Delta", value=-0.25, unit="Å", evidence=e.id), scope)
    with pytest.raises(ValidationError):
        validate(Number(name="Invented", value=987654.0, unit=None, evidence=e.id), scope)


def test_capture_origin_preserves_initial_reference_and_real_event_dates(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = ProjectConfig(id="p", name="P", root=str(root))
    now = datetime(2026, 11, 4, 19, tzinfo=UTC)
    with closing(connect(tmp_path / "db")) as db:
        context = CaptureContext(tmp_path / "data", now)
        persist(db, project, "test", CollectorOutput(status="failed"), context)
        initial = EvidenceDraft("doc_change", "initial", "old content", "Old conclusion", now)
        persist(db, project, "test", CollectorOutput(evidence=[initial]), context)
        change = EvidenceDraft("doc_change", "changed", "new content", "Changed conclusion", now)
        event = EvidenceDraft("commit", "commit", "dated", "Dated event", now, now)
        persist(db, project, "test", CollectorOutput(evidence=[initial, change, event]), context)
        rows = db.execute(
            "SELECT locator,event_at,time_quality,meta FROM evidence ORDER BY rowid"
        ).fetchall()
    assert [json.loads(r[3])["capture_origin"] for r in rows] == [
        "initial_inventory",
        "observed_change",
        "dated_event",
    ]
    assert rows[-1][1] == now.isoformat() and rows[-1][2] == "event"
    historical = entry("history", "notebook_change", "old.ipynb")
    historical.meta["capture_origin"] = "initial_inventory"
    observation = normalize(historical)
    assert any("no se atribuye a trabajo de hoy" in s for s in observation["limitations"])
    assert any("no ejecutó" in s for s in observation["limitations"])
