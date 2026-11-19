"""Bad scoped conditions stay pending or are repaired before monitoring is kept."""

import copy
import html
import json
import re
from dataclasses import replace

import httpx
import pytest

from digest import queue
from digest.llm.client import Client
from digest.llm.router import Router
from digest.llm.validator import validate_report
from digest.report import builder
from digest.report.builder import enrich
from digest.report.completeness import require_complete
from tests.fixtures.llm import fake_response
from tests.integration.test_monitoring_hierarchy import inventory
from tests.integration.test_publication import config as config

SOURCE = "Comparar usa resultados existentes. Solo regenerar exige aceptar otro protocolo."
BAD = "Comparar exige aceptar el protocolo nuevo antes de empezar."
GOOD = "Comparar usa los resultados existentes; la aceptación corresponde solo a regenerarlos."


@pytest.mark.parametrize("repair", [False, True])
def test_scoped_condition_audit_blocks_or_repairs_a_cached_monitoring_candidate(
    config, monkeypatch, repair
):
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
        value = json.loads(fake_response(request).json()["choices"][0]["message"]["content"])
        if title == "WatchAssessment":
            feedback = package["context"].get("validation_feedback")
            value["limits"][0]["text"] = GOOD if repair and feedback else BAD
        if (
            title == "GroundingAudit"
            and package["context"]["candidate"]["limits"][0]["text"] == BAD
        ):
            value = {
                "approved": False,
                "issues": [
                    {
                        "rule": "unsupported_claim",
                        "field": ["limits", 0, "text"],
                        "evidence": package["context"]["candidate"]["limits"][0]["evidence"],
                        "source_quote": "Solo regenerar exige aceptar otro protocolo.",
                    }
                ],
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    generate = Router.generate

    def controlled(self, *args, **kwargs):
        self.client = Client(transport=httpx.MockTransport(respond))
        return generate(self, *args, **kwargs)

    monkeypatch.setattr(Router, "generate", controlled)
    with queue.writing(config) as db:
        report = inventory(config, db, count=1)
        report.evidence[0].excerpt = SOURCE
        frozen = copy.deepcopy(report)
        enrich(db, config, report, Router(db, config))
        key = "watch:" + report.watchlist["items"][0]["id"]
        validate_report(report, {e.id for e in report.evidence})
        assert calls.count("WatchAssessment") == 2
        if not repair:
            assert key in report.pending and key not in report.sections
            with pytest.raises(ValueError):
                require_complete(report)
            return
        require_complete(report)
        assert report.sections[key]["limits"][0]["text"] == GOOD
        assert report.sections["check:" + key]["approved"]
        # An audit revision rechecks cached candidates without another generation.
        original_load = builder.load

        def revised(*args, **kwargs):
            prompt = original_load(*args, **kwargs)
            return (
                replace(prompt, version=prompt.version + "-test")
                if prompt.name == "grounding_watchlist"
                else prompt
            )

        monkeypatch.setattr(builder, "load", revised)
        calls.clear()
        enrich(db, config, frozen, Router(db, config))
        require_complete(frozen)
        validate_report(frozen, {e.id for e in frozen.evidence})
        assert calls and set(calls) == {"GroundingAudit"}
        assert frozen.sections[key]["limits"][0]["text"] == GOOD
        assert frozen.model_info[key]["reused"] == "true"
        assert frozen.model_info["check:" + key]["reused"] == "false"
        assert frozen.evidence[0].excerpt == SOURCE


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize(
    "field,source,bad,good,quote",
    [
        *[
            (
                field,
                "Para regenerar con otro protocolo, decidir antes si se aceptan los cambios. "
                "Otras vías son localizar archivos existentes o entregar el paquete externo.",
                "Toda recuperación exige aceptar cambios de protocolo.",
                "Solo regenerar con otro protocolo requiere decidir antes si se aceptan los "
                "cambios; localizar archivos o entregar el paquete son vías distintas.",
                "decidir antes si se aceptan los cambios",
            )
            for field in ["controls", "limitations", "interpretations"]
        ],
        (
            "controls",
            "Una posible vía de recuperación es usar otro alineamiento.",
            "Recuperar exige usar otro alineamiento.",
            "Usar otro alineamiento es una posible vía de recuperación.",
            "Una posible vía de recuperación",
        ),
        (
            "limitations",
            "Si el cristal carece del tramo, la predicción podría ser comparable tras alinear.",
            "Todas las predicciones requieren alinear para comprobarlas.",
            "La comparabilidad tras alinear se plantea solo si el cristal carece del tramo.",
            "Si el cristal carece del tramo",
        ),
        (
            "summary",
            "Se produjo un informe y un paquete. Quedan comprobaciones pendientes.",
            "El informe y el paquete acreditan el cierre del trabajo.",
            "Hay un informe y un paquete; las comprobaciones siguen pendientes.",
            "Quedan comprobaciones pendientes.",
        ),
    ],
)
def test_source_modality_errors_stay_pending_or_are_repaired(
    config, monkeypatch, repair, field, source, bad, good, quote
):
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
        value = json.loads(fake_response(request).json()["choices"][0]["message"]["content"])
        if title == "SourceFindings":
            refs = value["summary"]["evidence"]
            fixed = repair and package["context"].get("validation_feedback")
            claim = {"text": good if fixed else bad, "evidence": refs}
            if field == "interpretations":
                claim["confidence"] = "low"
            value[field] = claim if field == "summary" else [claim]
        candidate = package["context"].get("candidate", {})
        claims = candidate.get(field, [])
        if isinstance(claims, dict):
            claims = [claims]
        if title == "GroundingAudit" and claims and claims[0].get("text") == bad:
            value = {
                "approved": False,
                "issues": [
                    {
                        "rule": "unsupported_claim",
                        "field": [field, "text"] if field == "summary" else [field, 0, "text"],
                        "evidence": claims[0]["evidence"],
                        "source_quote": quote,
                    }
                ],
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    generate = Router.generate

    def controlled(self, *args, **kwargs):
        self.client = Client(transport=httpx.MockTransport(respond))
        return generate(self, *args, **kwargs)

    monkeypatch.setattr(Router, "generate", controlled)
    with queue.writing(config) as db:
        report = inventory(config, db, count=1)
        report.evidence[0].excerpt = source
        report.evidence[0].kind = "doc_change"
        report.evidence[0].event_at = report.end_at
        report.evidence[0].meta["capture_origin"] = "dated_event"
        enrich(db, config, report, Router(db, config))
        key = report.source_units[report.results[0].id][0]
        validate_report(report, {e.id for e in report.evidence})
        assert calls.count("SourceFindings") == 2
        assert report.evidence[0].excerpt == source
        assert report.results[0].review_state == "pending"
        if repair:
            require_complete(report)
            kept = report.sections[key][field]
            assert (kept["text"] if field == "summary" else kept[0]["text"]) == good
            assert report.sections["check:" + key]["approved"]
        else:
            assert key in report.pending and key not in report.sections
            assert "extract:" + report.results[0].id not in report.sections
            with pytest.raises(ValueError):
                require_complete(report)
