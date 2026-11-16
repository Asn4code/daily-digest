"""Human questions remain versioned, bounded and grounded across report channels."""

import asyncio
import copy
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from digest import queue, watchlist
from digest.db import connect
from digest.llm.schemas import WatchAssessment
from digest.llm.validator import EvidencePackage, ValidationError, validate, validate_report
from digest.publish.email import compose
from digest.report.completeness import missing_sections, require_complete
from digest.report.loading import load_ready
from digest.report.model import Report
from digest.report.monitoring import view
from digest.report.render_html import render as render_html
from digest.report.render_md import render as render_md
from digest.web.app import create_app
from digest.worker import enqueue, execute
from tests.e2e.test_plan_decisions import Forms
from tests.e2e.test_web_reading import request
from tests.integration.test_fixtures import _snapshot
from tests.integration.test_publication import NOW
from tests.integration.test_publication import config as config


def add(config, questions=None, **changes):
    values = watchlist.draft(
        questions
        or "Semillas por modelo\nResultados de dinámicas moleculares\nErrores con cristales",
        [config.projects[0].id],
        50,
    )
    values = [{**value, **changes} for value in values]
    with queue.writing(config) as db:
        return watchlist.save(db, config, values, watchlist.expected(db), secrets.token_hex(16))


def generated(config, kind="daily"):
    job = enqueue(config, kind, params={"no_send": True})
    path = Path(execute(config, job, now=NOW))
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        report, _, _ = load_ready(
            db, config, json.loads(path.with_suffix(".json").read_text())["id"]
        )
    return report, path, job


def test_list_edits_history_replay_and_stale_forms_preserve_human_text(config):
    ids = add(config)
    with queue.writing(config) as db:
        before = watchlist.catalogue(db)
        item = next(s for s in before if s["item_id"] == ids[0])
        expected = watchlist.expected(db)
        nonce = secrets.token_hex(16)
        values = [{**item["values"], "priority": 90, "question": "¿Qué semillas faltan?"}]
        assert watchlist.save(db, config, values, expected, nonce, item_id=ids[0]) == [ids[0]]
        assert watchlist.save(db, config, values, expected, nonce, item_id=ids[0]) == [ids[0]]
        with pytest.raises(ValueError):
            watchlist.save(db, config, values, expected, secrets.token_hex(16), item_id=ids[0])
        with pytest.raises(ValueError):
            watchlist.save(
                db, config, [{**values[0], "priority": 20}], expected, nonce, item_id=ids[0]
            )
        versions, more = watchlist.history(db, ids[0], 1)
        assert len(versions) == 2 and not more
        assert versions[0]["original"] == versions[1]["values"]
        assert versions[0]["first_created_at"] == versions[1]["first_created_at"]
        assert versions[0]["values"]["priority"] == 90


@pytest.mark.parametrize(
    "change",
    [
        {"priority": 101},
        {"priority": -1},
        {"question": " "},
        {"question": "x" * 1001},
        {"projects": ["unknown"]},
        {"state": "done"},
        {"title": "bad\x00text"},
    ],
)
def test_invalid_inputs_never_create_an_item(config, change):
    with pytest.raises(ValueError):
        add(config, "Una pregunta", **change)
    with queue.writing(config) as db:
        assert watchlist.catalogue(db) == []


def test_pause_archive_scope_and_budget_keep_all_active_items_visible(config):
    ids = add(config, "\n".join("Pregunta " + str(i) + " " + "x" * 960 for i in range(30)))
    with queue.writing(config) as db:
        frozen = watchlist.freeze(db, config)
        assert len(frozen["items"]) == 30
        assert any(s["omitted"] == "budget" for s in frozen["items"])
        with pytest.raises(ValueError):
            watchlist.save(
                db,
                config,
                watchlist.draft("Otra", [], 50),
                watchlist.expected(db),
                secrets.token_hex(16),
            )
        item = next(s for s in watchlist.catalogue(db) if s["item_id"] == ids[0])
        watchlist.save(
            db,
            config,
            [{**item["values"], "state": "paused"}],
            watchlist.expected(db),
            secrets.token_hex(16),
            item_id=ids[0],
        )
        assert len(watchlist.freeze(db, config)["items"]) == 29
        assert len(watchlist.history(db, ids[0], 1)[0]) == 2


def test_missing_policy_never_sends_human_question(config):
    ident = add(config, "CONFIDENTIAL QUESTION")[0]
    with queue.writing(config) as db:
        db.execute(
            "INSERT INTO project VALUES ('removed','Removed','/removed','objective',1,0,'x')"
        )
        frozen = watchlist.freeze(db, config)
    assert frozen["items"][0]["omitted"] == "privacy"
    report, _, _ = generated(config)
    assert not any(key.startswith("watch:") for key in report.sections)
    assert view(report)["pending"] == 1
    assert "política de privacidad" in render_md(report)
    with queue.writing(config) as db:
        assert db.execute(
            "SELECT value FROM meta WHERE key=?", ("wl_report:" + report.id + ":" + ident,)
        ).fetchone()
    assert report.id in request(create_app(config), path="/watchlist/" + ident).text


@pytest.mark.parametrize("kind", ["daily", "weekly"])
def test_benchmark_questions_are_validated_in_daily_and_weekly_and_all_channels(config, kind):
    before = [_snapshot(Path(p.root), include_git=True) for p in config.projects]
    ids = add(config)
    report, path, _ = generated(config, kind)
    assert len(report.watchlist["items"]) == 3
    for ident in ids:
        key = "watch:" + ident
        assert key in report.sections and "check:" + key in report.sections
        context = report.packages[key]["context"]
        assert context["mode"] == ("weekly_critical" if kind == "weekly" else "daily")
        assert report.sections[key]["status"] == "insufficient"
    target = "weekly" if kind == "weekly" else "plan"
    assert len(report.packages[target]["context"]["requested_monitoring"]) == 3
    require_complete(report)
    assert "Seguimiento solicitado" in path.read_text()
    assert "Evidencia insuficiente" in render_html(report)
    message = compose(config, report, path.parent)
    plain = message.get_body(preferencelist=("plain",)).get_content()
    assert "3 temas activos" in plain and "#watchlist" in plain
    assert "Semillas por modelo" in plain
    assert "Seguimiento solicitado" in message.get_body(preferencelist=("html",)).get_content()
    app = create_app(config)
    assert request(app, path="/reports/" + report.id).status_code == 200
    assert request(app, path="/watchlist/" + ids[0]).status_code == 200
    assert [_snapshot(Path(p.root), include_git=True) for p in config.projects] == before


def test_T14_list_preview_requires_confirmation_and_escapes_human_html(config):
    async def run():
        app = create_app(config)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1",
        ) as client:
            initial = await client.get("/watchlist")
            forms = Forms()
            forms.feed(initial.text)
            form = forms.forms[0]
            form.update(
                text="<script>alert('human')</script>\nDinámicas moleculares",
                projects=config.projects[0].id,
                priority="70",
            )
            assert (
                await client.post(
                    "/watchlist/preview", data={k: v for k, v in form.items() if k != "csrf_token"}
                )
            ).status_code == 403
            preview = await client.post("/watchlist/preview", data=form)
            assert preview.status_code == 200 and "&lt;script&gt;" in preview.text
            assert "<script>alert" not in preview.text
            with queue.writing(config) as db:
                assert not watchlist.catalogue(db)
            forms = Forms()
            forms.feed(preview.text)
            saved = await client.post("/watchlist/save", data=forms.forms[0])
            assert saved.status_code == 303
            assert (await client.post("/watchlist/save", data=forms.forms[0])).status_code == 303
            with queue.writing(config) as db:
                assert len(watchlist.catalogue(db)) == 2
                assert db.execute("SELECT count(*) FROM job").fetchone()[0] == 0

    asyncio.run(run())


def assessment(eid):
    claim = {"text": "La evidencia requiere contraste.", "evidence": [eid]}
    return WatchAssessment.model_validate(
        {
            "status": "insufficient",
            "finding": claim,
            "meaning": {**claim, "confidence": "low"},
            "limits": [claim],
            "next_check": claim,
            "current_evidence": [],
        }
    )


def test_invented_or_historical_news_and_unsupported_absence_are_rejected(config):
    add(config, "Pregunta")
    report, _, _ = generated(config)
    eid = report.evidence[0].id
    value = assessment(eid)
    package = EvidencePackage({e.id: e for e in report.evidence}, {p.id for p in config.projects})
    for status in ("news", "no_new"):
        value.status = status
        with pytest.raises(ValidationError):
            validate(value, package)
    value.status = "insufficient"
    value.current_evidence = ["invented"]
    with pytest.raises(ValidationError):
        validate(value, package)


def test_tampered_question_and_changed_coverage_cannot_be_published(config):
    add(config, "Pregunta")
    report, _, _ = generated(config)
    altered = copy.deepcopy(report)
    altered.watchlist["items"][0]["values"]["question"] = "Changed"
    with pytest.raises(ValueError):
        validate_report(altered, {e.id for e in altered.evidence})
    altered = copy.deepcopy(report)
    key = next(k for k in report.sections if k.startswith("watch:"))
    altered.packages[key]["context"]["watch_item"]["revision"] = "changed"
    with pytest.raises(ValueError):
        validate_report(altered, {e.id for e in altered.evidence})
    altered = copy.deepcopy(report)
    altered.packages[key]["context"]["coverage_complete"] = not altered.packages[key]["context"][
        "coverage_complete"
    ]
    with pytest.raises(ValueError):
        validate_report(altered, {e.id for e in altered.evidence})
    altered = copy.deepcopy(report)
    altered.sections.pop(key)
    assert key in missing_sections(altered)
    with pytest.raises(ValueError):
        require_complete(altered)


def test_no_evidence_and_package_omissions_remain_explicit(config):
    add(config, "Una pregunta")
    with queue.writing(config) as db:
        frozen = watchlist.freeze(db, config)
    report = Report(
        "empty", "daily", NOW.isoformat(), NOW.isoformat(), NOW.isoformat(), watchlist=frozen
    )
    assert view(report)["pending"] == 1
    assert "no demuestra ausencia de trabajo" in render_md(report)


def test_frozen_inventory_does_not_follow_later_edits(config):
    ids = add(config, "Pregunta original")
    report, _, job = generated(config)
    with queue.writing(config) as db:
        original = watchlist.catalogue(db)[0]
        watchlist.save(
            db,
            config,
            [{**original["values"], "question": "Pregunta posterior"}],
            watchlist.expected(db),
            secrets.token_hex(16),
            item_id=ids[0],
        )
        params = json.loads(db.execute("SELECT params FROM job WHERE id=?", (job,)).fetchone()[0])
        from digest.report.inventory import load

        frozen = load(config, job, params["inventory_hash"])
        assert frozen.watchlist == report.watchlist
        assert frozen.watchlist["items"][0]["values"]["question"] == "Pregunta original"
        assert watchlist.freeze(db, config) != frozen.watchlist


def test_older_reports_without_watchlist_remain_readable(config):
    report, _, _ = generated(config)
    assert not report.watchlist["items"]
    data = asdict(report)
    data.pop("watchlist")
    from pydantic import TypeAdapter

    old = TypeAdapter(Report).validate_python(data)
    validate_report(old, {e.id for e in old.evidence})
    assert "Seguimiento solicitado" not in render_md(old)


def test_concurrent_updates_keep_one_revision_and_rollback_a_failed_batch(config):
    ident = add(config, "Pregunta original")[0]
    with queue.writing(config) as db:
        item = watchlist.catalogue(db)[0]
        etag = watchlist.expected(db)

    def change(priority):
        try:
            with queue.writing(config) as db:
                watchlist.save(
                    db,
                    config,
                    [{**item["values"], "priority": priority}],
                    etag,
                    secrets.token_hex(16),
                    item_id=ident,
                )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(change, [60, 70])) == 1
    with queue.writing(config) as db:
        assert len(watchlist.history(db, ident, 1)[0]) == 2
        etag = watchlist.expected(db)
        original = watchlist.append
        calls = 0

        def broken(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("Interrupted batch")
            return original(*args, **kwargs)

        with patch.object(watchlist, "append", broken), pytest.raises(ValueError):
            watchlist.save(
                db, config, watchlist.draft("Una\nOtra", [], 50), etag, secrets.token_hex(16)
            )
        assert watchlist.expected(db) == etag and len(watchlist.catalogue(db)) == 1


def test_historical_privacy_is_not_lost_after_removing_and_restoring_a_project(config):
    removed = config.projects[0].model_copy(update={"id": "private", "external_allowed": False})
    config.projects.append(removed)
    ident = add(config, "Nota humana general", projects=[])[0]
    config.projects.pop()
    with queue.writing(config) as db:
        item = watchlist.catalogue(db)[0]
        watchlist.save(
            db,
            config,
            [{**item["values"], "question": "Pregunta editada"}],
            watchlist.expected(db),
            secrets.token_hex(16),
            item_id=ident,
        )
        frozen = watchlist.freeze(db, config)
        assert frozen["items"][0]["omitted"] == "privacy"
        assert "private" in frozen["items"][0]["privacy_projects"]
    config.projects.append(removed)
    with queue.writing(config) as db:
        assert watchlist.freeze(db, config)["items"][0]["omitted"] is None


def test_no_new_requires_an_earlier_successful_baseline_and_complete_coverage(config):
    add(config, "Pregunta")
    report, _, _ = generated(config)
    key = next(k for k in report.sections if k.startswith("watch:"))
    from digest.report.builder import package_scope

    scope = package_scope(report.packages[key])
    value = WatchAssessment.model_validate(report.sections[key])
    value.status = "no_new"
    prior = {
        "revision": scope.watch_context["watch_item"]["revision"],
        "end_at": report.start_at,
        "assessment": {**report.sections[key], "status": "news"},
    }
    scope.watch_context.update(previous=prior, coverage_complete=True)
    validate(value, scope)
    for update in [
        {"coverage_complete": False},
        {"previous": {**prior, "end_at": report.end_at}},
        {"previous": {**prior, "revision": "different"}},
        {"previous": {**prior, "assessment": report.sections[key]}},
    ]:
        bad = copy.deepcopy(scope)
        bad.watch_context.update(update)
        with pytest.raises(ValueError):
            validate(value, bad)


def test_history_uses_exact_question_revision_and_preserves_evidence(config):
    ident = add(config, "Pregunta original")[0]
    report, _, _ = generated(config)
    from digest.report.monitoring import previous

    next_report = copy.deepcopy(report)
    next_report.start_at = report.end_at
    with queue.writing(config) as db:
        prior, ids, scope = previous(db, config, next_report, report.watchlist["items"][0])
        assert prior["report_id"] == report.id and ids and scope
        item = watchlist.catalogue(db)[0]
        watchlist.save(
            db,
            config,
            [{**item["values"], "question": "Otra pregunta"}],
            watchlist.expected(db),
            secrets.token_hex(16),
            item_id=ident,
        )
        changed = watchlist.freeze(db, config)["items"][0]
        assert previous(db, config, next_report, changed) == (None, set(), set())


def test_model_failure_leaves_monitoring_pending_without_final_delivery(config):
    add(config, "Pregunta")
    from digest.llm.router import Router

    original = Router.generate

    def fail_watch(self, task, **kwargs):
        if kwargs.get("prompt_name") == "watchlist":
            return None
        return original(self, task, **kwargs)

    job = enqueue(config, "daily", params={"no_send": True})
    with patch.object(Router, "generate", fail_watch):
        draft_path = Path(execute(config, job, now=NOW))
    assert draft_path.name == "draft.md"
    draft = json.loads(draft_path.with_suffix(".json").read_text())
    assert any(key.startswith("watch:") for key in draft["pending"])
    with queue.writing(config) as db:
        params = json.loads(db.execute("SELECT params FROM job WHERE id=?", (job,)).fetchone()[0])
        assert (
            db.execute("SELECT status FROM report WHERE id=?", (params["report_id"],)).fetchone()[0]
            != "ready"
        )
        assert db.execute("SELECT count(*) FROM delivery").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM interval WHERE closed=1").fetchone()[0] == 0
        saved = watchlist.catalogue(db)[0]
        watchlist.save(
            db,
            config,
            [{**saved["values"], "question": "Edición posterior"}],
            watchlist.expected(db),
            secrets.token_hex(16),
            item_id=saved["item_id"],
        )
    from digest.worker import resume

    resume(config, job, no_send=True)
    path = Path(execute(config, job, now=NOW))
    result = json.loads(path.with_suffix(".json").read_text())
    assert result["watchlist"]["items"][0]["values"]["question"] == "Pregunta"


def test_stable_day_can_compare_previous_news_without_inventing_new_evidence(config):
    add(config, "Pregunta")
    from digest.llm.client import Client
    from digest.llm.router import Router
    from digest.report.builder import enrich

    original = Client.complete

    def classified(self, provider, messages, schema, **kwargs):
        response = original(self, provider, messages, schema, **kwargs)
        if schema and schema.get("title") == "WatchAssessment":
            response.value["status"] = "news" if response.value["current_evidence"] else "no_new"
        return response

    with patch.object(Client, "complete", classified):
        report, _, _ = generated(config)
        assert all(c.status == "ok" and not c.omitted for c in report.coverage)
        follow = Report(
            "stable",
            "daily",
            report.end_at,
            (NOW + timedelta(days=1)).isoformat(),
            (NOW + timedelta(days=1)).isoformat(),
            coverage=copy.deepcopy(report.coverage),
            watchlist=copy.deepcopy(report.watchlist),
        )
        with queue.writing(config) as db:
            enrich(db, config, follow, Router(db, config))
    key = next(k for k in follow.sections if k.startswith("watch:"))
    assert follow.sections[key]["status"] == "no_new"
    assert follow.sections[key]["current_evidence"] == []
    assert all(e.context_only for e in follow.evidence)
    validate_report(follow, {e.id for e in follow.evidence})
    require_complete(follow)
