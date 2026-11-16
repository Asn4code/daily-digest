"""Large monitoring inventories reduce by validated pieces without dropping inputs."""

import copy
import json
from dataclasses import asdict

import pytest

from digest.llm.monitoring import MonitoringContext
from digest.report.model import EvidenceEntry, Report, ResultEntry
from digest.report.monitoring_tree import build, quoted_parent, required, verify


def sample(count=2600):
    date = "2026-11-16T12:00:00+00:00"
    item = {
        "id": "wl_" + "a" * 32,
        "revision": "nb_" + "b" * 32,
        "values": {
            "title": "Pregunta",
            "question": "¿Qué se puede comprobar?",
            "projects": ["p"],
            "priority": 50,
            "state": "active",
        },
        "projects": ["p"],
        "privacy_projects": ["p", "private"],
        "omitted": None,
    }
    report = Report("large", "preview", date, date, date, watchlist={"items": [item]})
    for i in range(count):
        report.evidence.append(
            EvidenceEntry(
                "ev_" + str(i),
                "p",
                "structure",
                "models/protein_" + str(i) + "/model.pdb",
                "Una observación con condiciones documentadas. " + "x" * 700,
                date,
                date,
                "event",
                {"path": "models/protein_" + str(i) + "/model.pdb"},
            )
        )
    report.results.append(
        ResultEntry("result", "p", "Resultados", None, "pending", [e.id for e in report.evidence])
    )
    context = {
        "watch_item": item,
        "interval": {"start": date, "end": date},
        "mode": "daily",
        "previous": None,
        "coverage_complete": False,
        "current_evidence_ids": [e.id for e in report.evidence],
    }
    return report, item, context


class FakeGeneration:
    def __init__(self, report, fail=None):
        self.report = report
        self.fail = fail
        self.calls = []

    def measure(self, prompt, ids, scope, context, results, mode):
        entries = [e for e in self.report.evidence if e.id in ids]
        evidence = (
            [asdict(e) for e in entries]
            if mode == "full"
            else [{"id": e.id, "project": e.project, "kind": e.kind} for e in entries]
        )
        return len(json.dumps({"evidence": evidence, "context": context}, ensure_ascii=False))

    def __call__(self, task, key, ids, scope, context, results, **options):
        mode = options.get("wire_mode", "full")
        size = self.measure(options["prompt_name"], ids, scope, context, results, mode)
        assert size <= options["char_limit"]
        self.calls.append((key, ids, scope, context, mode))
        if self.fail and self.fail in key:
            return
        claim = {"text": "Hay una fuente documentada.", "evidence": ids[:1]}
        if options["contract"] == "watchctx":
            value = MonitoringContext.model_validate(
                {
                    "observations": [claim],
                    "interpretations": [],
                    "controls": [],
                    "limits": [{**claim, "text": "No acredita ejecución por sí sola."}],
                    "open_questions": [],
                }
            ).model_dump()
        else:
            value = {
                "status": "insufficient",
                "finding": claim,
                "meaning": {**claim, "confidence": "low"},
                "limits": [claim],
                "next_check": claim,
                "current_evidence": ids[:1],
            }
        self.report.sections[key] = value
        self.report.packages[key] = {
            "evidence": [asdict(e) for e in self.report.evidence if e.id in ids],
            "project_ids": sorted(scope),
            "parents": context.get("_parents", []),
            "context": {k: v for k, v in context.items() if not k.startswith("_")},
            "wire_mode": mode,
        }


def generate(report, item, context, *, fail=None, limit=6000):
    fake = FakeGeneration(report, fail)
    build(
        report,
        fake,
        fake.measure,
        item,
        {e.id for e in report.evidence},
        {"p", "private"},
        context,
        deadline=float("inf"),
        limit=limit,
    )
    return fake


def test_large_initial_inventory_keeps_all_2600_sources_and_bounded_calls():
    report, item, context = sample()
    fake = generate(report, item, context)
    root = "watch:" + item["id"]
    assert root in report.sections and not report.pending
    assert len(report.evidence) == 2600 and len(report.results[0].evidence) == 2600
    tree = report.human_context["watch_trees"][item["id"]]
    assert set(tree["inputs"]) == {e.id for e in report.evidence}
    assert any(n["kind"] == "reduction" for n in tree["nodes"].values())
    assert all(call[2] == {"p", "private"} for call in fake.calls)
    assert required(report) == set(tree["nodes"])
    verify(report)


def test_missing_source_blocks_its_reductions_and_final_assessment():
    report, item, context = sample(30)
    generate(report, item, context, fail=":source:")
    assert "watch:" + item["id"] not in report.sections
    assert report.pending["watch:" + item["id"]][0]["rule"] == "monitoring_source_pending"
    assert all(
        n["kind"] == "source"
        for n in report.human_context["watch_trees"][item["id"]]["nodes"].values()
    )
    verify(report)


def test_whole_coherent_unit_too_large_is_pending_without_cutting_it():
    report, item, context = sample(15)
    for e in report.evidence:
        e.meta["path"] = "same-experiment/" + e.id + ".pdb"
    fake = generate(report, item, context)
    assert not fake.calls
    assert any(
        issues[0]["rule"] == "monitoring_coherent_unit_budget" for issues in report.pending.values()
    )
    tree = report.human_context["watch_trees"][item["id"]]
    assert set(tree["nodes"][tree["leaves"][0]]["inputs"]) == {e.id for e in report.evidence}
    verify(report)


@pytest.mark.parametrize(
    "mutation", ["missing_input", "forged_parent", "cycle", "scope", "missing_leaf"]
)
def test_manifests_and_exact_parent_binding_cannot_be_forged(mutation):
    report, item, context = sample(40)
    generate(report, item, context)
    tree = report.human_context["watch_trees"][item["id"]]
    root = tree["root"]
    if mutation == "missing_input":
        tree["inputs"].pop()
    elif mutation == "forged_parent":
        parent = next(iter(report.packages[root]["context"]["parent_pieces"]))
        report.packages[root]["context"]["parent_pieces"][parent] = {"forged": True}
    elif mutation == "cycle":
        tree["nodes"][root]["parents"].append(root)
    elif mutation == "scope":
        report.packages[root]["project_ids"] = ["p"]
    else:
        tree["leaves"].pop()
    with pytest.raises(ValueError):
        verify(report)


def test_derived_audit_can_only_quote_a_cited_parent_claim():
    claim = {"text": "El control sigue pendiente según la fuente.", "evidence": ["ev_a"]}
    context = {"derived_monitoring": True, "parent_pieces": {"parent": {"limits": [claim]}}}
    assert quoted_parent("control sigue pendiente", ["ev_a"], context)
    assert not quoted_parent("control sigue pendiente", ["ev_b"], context)
    assert not quoted_parent("una afirmación inventada", ["ev_a"], context)
    assert not quoted_parent(
        "control sigue pendiente", ["ev_a"], {**context, "derived_monitoring": False}
    )
    changed = copy.deepcopy(context)
    changed["parent_pieces"] = {"note": "control sigue pendiente"}
    assert not quoted_parent("control sigue pendiente", ["ev_a"], changed)
