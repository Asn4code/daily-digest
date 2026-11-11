"""Explicit focus decisions, immutable exports and continuity into later reports."""

import asyncio
import json
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from digest import planning
from digest.db import connect
from digest.llm.client import Client
from digest.publish.plan import publish
from digest.report.builder import task_context
from digest.report.context import human_context
from digest.review import records
from digest.web.app import create_app
from digest.worker import execute
from tests.integration.test_publication import NOW, build
from tests.integration.test_publication import config as config


@pytest.fixture
def report(config, monkeypatch):
    original = Client.complete

    def complete(self, provider, messages, schema, **kwargs):
        response = original(self, provider, messages, schema, **kwargs)
        if schema and schema.get("title") == "TomorrowPlan" and response.value["mission"]:
            mission = response.value["mission"]
            response.value["warmups"] = [
                {
                    key: ("warmup" if key == "kind" else title if key == "action" else mission[key])
                    for key in (
                        "kind",
                        "project_id",
                        "action",
                        "done_criterion",
                        "dependency",
                        "reason",
                        "origin",
                        "kanvas_task_id",
                        "evidence",
                    )
                }
                for title in ("Reconocer el control", "Comparar las condiciones")
            ]
        return response

    monkeypatch.setattr(Client, "complete", complete)
    ident = build(config, since=NOW.replace(hour=0), until=NOW)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        return records.document(db, config, ident)


def decide(config, report, index=0, action="accept", changes=None, expected=None, submission=None):
    with records.writing(config) as db:
        item = planning.items(db, report)[index]
        values = {k: item[k] or "" for k in ("action", "done_criterion", "dependency")}
        values.update(changes or {})
        return planning.decide(
            db,
            config,
            report.id,
            item["id"],
            action,
            values,
            expected or planning.token(db, config, report),
            submission or "a" * 32,
        )


class Forms(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None
        self.textarea = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form":
            self.current = {}
            self.forms.append(self.current)
        if self.current is not None and tag == "input":
            self.current[values["name"]] = values["value"]
        if self.current is not None and tag == "textarea":
            self.textarea = values["name"]
            self.current[self.textarea] = ""

    def handle_data(self, text):
        if self.textarea:
            self.current[self.textarea] += text

    def handle_endtag(self, tag):
        if tag == "textarea":
            self.textarea = None
        if tag == "form":
            self.current = None


def test_web_accepts_human_edits_without_running_jobs_or_closing_reviews(config, report):
    async def run():
        app = create_app(config)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1",
            follow_redirects=True,
        ) as client:
            page = await client.get("/plan/2026-11-04")
            assert page.status_code == 200 and "Elige en qué avanzar" in page.text
            forms = Forms()
            forms.feed(page.text)
            form = forms.forms[0]
            form.update(
                action='Mi foco <script>alert("x")</script>',
                done_criterion="Comparación con su control",
                dependency="Esperar el control",
                decision="accept",
            )
            missing = {k: v for k, v in form.items() if k != "csrf_token"}
            assert (
                await client.post(f"/reports/{report.id}/plan", data=missing)
            ).status_code == 403
            accepted = await client.post(f"/reports/{report.id}/plan", data=form)
            assert accepted.status_code == 200 and "Propuesta aceptada" in accepted.text
            assert "<script>alert" not in accepted.text and "&lt;script&gt;" in accepted.text
            assert (await client.post(f"/reports/{report.id}/plan", data=form)).url == accepted.url
            with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
                chosen = planning.active(db, config)
                assert chosen[0]["action"] == form["action"]
                assert chosen[0]["done_criterion"] == form["done_criterion"]
                assert (
                    db.execute("SELECT count(*) FROM job WHERE kind='deliver'").fetchone()[0] == 1
                )
                assert (
                    db.execute(
                        "SELECT count(*) FROM result WHERE review_state='closed_by_human'"
                    ).fetchone()[0]
                    == 0
                )
            assert not (Path(config.paths.data_dir) / "plans").exists()

    asyncio.run(run())


def test_saving_an_adjustment_does_not_accept_and_old_versions_are_kept(config, report):
    first = decide(config, report, action="save", changes={"action": "Mi ajuste"})
    second = decide(
        config,
        report,
        action="accept",
        changes={"action": "Mi elección posterior"},
        submission="b" * 32,
    )
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert planning.snapshot(db, config, first)["active"] == []
        assert planning.snapshot(db, config, first)["item"]["action"] == "Mi ajuste"
        assert (
            planning.snapshot(db, config, second)["active"][0]["action"] == "Mi elección posterior"
        )
        assert (
            db.execute("SELECT edited_text FROM plan_item WHERE kind='mission'").fetchone()[0]
            == "Mi elección posterior"
        )


def test_stale_form_and_foreign_item_are_rejected_without_extra_decisions(config, report):
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        old = planning.token(db, config, report)
    decide(config, report)
    with pytest.raises(ValueError, match="reload"):
        decide(config, report, action="dismiss", expected=old, submission="b" * 32)
    with records.writing(config) as db, pytest.raises(ValueError):
        planning.decide(
            db,
            config,
            report.id,
            -1,
            "accept",
            {"action": "A", "done_criterion": "B", "dependency": ""},
            planning.token(db, config, report),
            "c" * 32,
        )


def test_worker_exports_exact_snapshot_even_if_focus_changes_before_delivery(config, report):
    first = decide(config, report, changes={"action": "Primera elección"})
    second = decide(config, report, changes={"action": "Segunda elección"}, submission="b" * 32)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        jobs = [r[0] for r in db.execute("SELECT id FROM job WHERE kind='deliver' ORDER BY id")]
    for job in jobs:
        execute(config, job, now=NOW)
    vault = Path(config.paths.obsidian_vault) / "Planes"
    first_note = next(vault.glob("*-" + first + ".md"))
    original = first_note.read_bytes()
    assert (
        "Primera elección" in first_note.read_text()
        and "Segunda elección" not in first_note.read_text()
    )
    assert "Segunda elección" in next(vault.glob("*-" + second + ".md")).read_text()
    remote = Path(config.drive.remote.removeprefix(":local:")) / "plans" / first
    assert (
        json.loads((remote / "plan.json").read_text())["active"][0]["action"] == "Primera elección"
    )
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        before = planning.meta(db, f"plan_delivery:{first}:drive")
        assert publish(db, config, first) == {"obsidian": "sent", "drive": "sent"}
        assert planning.meta(db, f"plan_delivery:{first}:drive") == before
    assert first_note.read_bytes() == original


def test_generated_revision_does_not_overwrite_the_accepted_human_plan(config, report):
    decide(
        config,
        report,
        changes={
            "action": "Mi misión concreta",
            "done_criterion": "Mi criterio comprobable",
            "dependency": "Mi control previo",
        },
    )
    ident = build(config, since=NOW.replace(hour=0), until=NOW)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        regenerated = records.document(db, config, ident)
        current = human_context(db, config, task_context(db, config))
    assert regenerated.sections["plan"]["carry_forward_id"] == current["accepted_plan"]["id"]
    assert current["accepted_plan"]["edited_text"] == "Mi misión concreta"
    assert current["accepted_plan"]["done_criterion"] == "Mi criterio comprobable"
    assert current["accepted_plan"]["dependency"] == "Mi control previo"
    note = Path(config.paths.data_dir) / "reports/daily" / ident / "report.md"
    assert (
        "Mi misión concreta" in note.read_text() and "Mi criterio comprobable" in note.read_text()
    )


def test_warmups_can_be_selected_without_forcing_a_mission(config, report):
    decide(config, report, index=1, changes={"action": "Mi calentamiento"})
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        context = human_context(db, config, {})
    assert context["accepted_plan"] is None
    assert context["accepted_warmups"][0]["edited_text"] == "Mi calentamiento"
    ident = build(config, since=NOW.replace(hour=0), until=NOW)
    note = Path(config.paths.data_dir) / "reports/daily" / ident / "report.md"
    assert "Mi calentamiento" in note.read_text()


def test_two_warmups_remain_the_limit_across_report_revisions(config, report):
    decide(config, report, index=1)
    decide(config, report, index=2, submission="b" * 32)
    ident = build(config, since=NOW.replace(hour=0), until=NOW)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        newer = records.document(db, config, ident)
    with pytest.raises(ValueError, match="at most two"):
        decide(config, newer, index=1, submission="c" * 32)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert len(planning.active(db, config)) == 2


def test_dismiss_removes_selection_but_not_its_history(config, report):
    first = decide(config, report)
    second = decide(config, report, action="dismiss", submission="b" * 32)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert planning.active(db, config) == []
        assert planning.snapshot(db, config, first)["active"]
        assert planning.snapshot(db, config, second)["active"] == []


def test_snapshot_changes_are_rejected_before_delivery(config, report):
    ident = decide(config, report)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        raw = planning.meta(db, "plan_snapshot:" + ident)
        raw["active"][0]["action"] = "Otra acción"
        db.execute(
            "UPDATE meta SET value=? WHERE key=?", (json.dumps(raw), "plan_snapshot:" + ident)
        )
        with pytest.raises(ValueError, match="changed"):
            publish(db, config, ident)
    assert not (Path(config.paths.data_dir) / "plans").exists()


@pytest.mark.parametrize("index", [0, 1])
def test_human_scope_cannot_shrink_when_a_private_project_is_removed(
    config, report, tmp_path, index
):
    private = config.projects[0].model_copy(
        update={"id": "private", "root": str(tmp_path / "private"), "external_allowed": False}
    )
    config.projects.append(private)
    decide(config, report, index=index, changes={"action": "Detalle del proyecto privado"})
    config.projects.pop()
    decide(
        config,
        report,
        index=index,
        changes={"action": "Detalle privado ajustado"},
        submission="b" * 32,
    )
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert not human_context(db, config, {})["scope_available"]


def test_failed_drive_does_not_repeat_the_vault_copy(config, report):
    ident = decide(config, report)
    from digest.util.proc import ProcessResult

    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        with patch("digest.publish.plan.run", return_value=ProcessResult(1, "", "")):
            assert publish(db, config, ident) == {"obsidian": "sent", "drive": "failed"}
        assert publish(db, config, ident) == {"obsidian": "sent", "drive": "sent"}
        assert planning.meta(db, f"plan_delivery:{ident}:obsidian")["attempts"] == 1
        assert planning.meta(db, f"plan_delivery:{ident}:drive")["attempts"] == 2


def test_plan_folder_cannot_redirect_to_other_vault_notes(config, report):
    ident = decide(config, report)
    vault = Path(config.paths.obsidian_vault)
    other = vault / "Personal"
    other.mkdir()
    (vault / "Planes").symlink_to(other, target_is_directory=True)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert publish(db, config, ident)["obsidian"] == "failed"
    assert list(other.iterdir()) == []
