"""A personal task notebook never writes project boards or declares understanding."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from digest import notebook, queue
from digest.config import load_config
from digest.db import connect
from digest.report.builder import task_context
from digest.report.daily import frontier
from digest.report.model import Report
from digest.web.app import create_app
from digest.web.notebook_graph import layout
from digest.worker import enqueue, execute
from tests.e2e.test_plan_decisions import Forms
from tests.e2e.test_web_reading import request
from tests.fixtures.make_projects import _kanvas, build_projects
from tests.fixtures.work import add_current_work
from tests.integration.test_fixtures import _snapshot

NOW = datetime(2026, 11, 4, 19, tzinfo=UTC)


@pytest.fixture
def config(tmp_path):
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:2]
    kanvas = _kanvas()
    kanvas.now_iso = lambda: "2026-10-01T09:00:00+00:00"
    for project in config.projects:

        def add(board):
            group = board["groups"][0]
            old = kanvas.add_task(
                board, "Comprobar el control previo", group, state="todo", by="fixture"
            )
            kanvas.add_task(
                board,
                "Comparar después del control",
                group,
                deps=[old["id"]],
                state="todo",
                by="fixture",
            )
            unknown = kanvas.add_task(
                board, "Sin fecha declarada", group, state="todo", by="fixture"
            )
            unknown["at"] = None
            kanvas.add_task(board, "Control terminado", group, state="done", by="fixture")
            future = kanvas.add_task(board, "Fecha futura", group, state="todo", by="fixture")
            future["at"] = "2027-01-01T00:00:00+00:00"
            unsafe = kanvas.add_task(
                board, '<script>alert("title")</script>', group, state="doing", by="fixture"
            )
            kanvas.add_note(unsafe, '<img src=x onerror=alert("note")>', "fixture-agent")

        kanvas.mutate(str(Path(project.root) / "kanvas.json"), add)
    add_current_work(config, extra_result=False)
    execute(config, enqueue(config, "capture"), now=NOW)
    yield config
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def save(
    config,
    task_id="AN-02",
    *,
    project_id=None,
    note="Mi nota",
    base=80,
    aging="inherit",
    nonce="a" * 32,
    expected=None,
):
    pid = project_id or config.projects[0].id
    with queue.writing(config) as db:
        current = notebook.task(db, config, pid, task_id, now=NOW)
        return notebook.save(
            db,
            config,
            pid,
            task_id,
            {"note": note, "base": base, "aging": aging},
            expected or current["expected"],
            nonce,
        )


def test_dates_aging_cap_unknown_dates_done_and_future_are_explicit(config):
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        pid = config.projects[0].id
        old = notebook.task(db, config, pid, "AN-02", now=NOW)
        unknown = notebook.task(db, config, pid, "AN-04", now=NOW + timedelta(days=3))
        done = notebook.task(db, config, pid, "AN-05", now=NOW)
        future = notebook.task(db, config, pid, "AN-06", now=NOW)
    assert old["suggested"] == 70 and old["aging_bonus"] == 20
    assert unknown["created_at"] is None and unknown["date_basis"] == "observed"
    assert unknown["age_days"] == 3 and unknown["suggested"] == 53
    assert done["aging_bonus"] == 0 and done["state"] == "done"
    assert future["future_date"] and future["age_days"] == 0 and future["suggested"] == 50


def test_priority_can_be_edited_after_creation_without_changing_kanvas(config):
    before = {p.id: _snapshot(Path(p.root), include_git=True) for p in config.projects}
    app = create_app(config)

    async def run():
        pid = config.projects[0].id
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1",
            follow_redirects=True,
        ) as client:
            page = await client.get(f"/notebook/{pid}/AN-02")
            parsed = Forms()
            parsed.feed(page.text)
            data = parsed.forms[0]
            data.update(base="95", aging="off", note="Mi foco con otro control")
            # Select elements are deliberately not parsed by this small fixture parser.
            assert (
                await client.post(
                    f"/notebook/{pid}/AN-02",
                    data={k: v for k, v in data.items() if k != "csrf_token"},
                )
            ).status_code == 403
            response = await client.post(f"/notebook/{pid}/AN-02", data=data)
            assert response.status_code == 200
            assert "Mi foco con otro control" in response.text and "Versión 1" in response.text
            repeated = await client.post(f"/notebook/{pid}/AN-02", data=data)
            assert repeated.status_code == 200 and "Versión 2" not in repeated.text

    asyncio.run(run())
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        item = notebook.task(db, config, config.projects[0].id, "AN-02", now=NOW)
        assert item["base"] == item["suggested"] == 95
        assert db.execute("SELECT count(*) FROM job").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM review").fetchone()[0] == 0
    assert before == {p.id: _snapshot(Path(p.root), include_git=True) for p in config.projects}


def test_notes_survive_recapture_and_history_keeps_every_human_version(config):
    first = save(config, note="Primera nota", base=90)
    execute(config, enqueue(config, "capture"), now=NOW + timedelta(hours=1))
    second = save(config, note="Segunda nota", base=60, nonce="b" * 32)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        item = notebook.task(db, config, config.projects[0].id, "AN-02", now=NOW)
        versions, more = notebook.history(db, config.projects[0].id, "AN-02")
        assert item["personal"]["note"] == "Segunda nota"
        assert [v["id"] for v in versions] == [second, first] and not more
        assert versions[1]["values"]["note"] == "Primera nota"


def test_same_task_id_in_different_projects_has_distinct_notes_and_graph_edges(config):
    a, b = [p.id for p in config.projects]
    save(config, project_id=a, note="Solo proyecto A")
    save(config, project_id=b, note="Solo proyecto B", nonce="b" * 32)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        tasks, _ = notebook.catalogue(db, config, now=NOW)
    assert (
        next(t for t in tasks if t["project_id"] == a and t["id"] == "AN-02")["personal"]["note"]
        == "Solo proyecto A"
    )
    graph = layout(tasks)
    assert len(graph["edges"]) == 2
    assert len({(n["task"]["project_id"], n["task"]["id"]) for n in graph["nodes"]}) == len(tasks)


def test_high_priority_never_unblocks_or_starts_a_task(config):
    save(config, "AN-03", base=100)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        item = notebook.task(db, config, config.projects[0].id, "AN-03", now=NOW)
        report = Report(
            "temporary",
            "daily",
            (NOW - timedelta(days=1)).isoformat(),
            NOW.isoformat(),
            NOW.isoformat(),
        )
        candidates, _, _ = frontier(db, config, report, task_context(db, config))
    assert item["suggested"] == 100 and item["blockers"] == ["AN-02"]
    assert not item["available"] and item["state"] == "todo"
    assert not any(c["id"] == "AN-03" and c["project_id"] == item["project_id"] for c in candidates)


def test_settings_can_disable_aging_without_overwriting_a_manual_base(config):
    save(config, base=95)
    with queue.writing(config) as db:
        notebook.save_settings(
            db, {"base": 10, "daily_step": 2, "cap": 5, "enabled": False}, None, "b" * 32
        )
        item = notebook.task(db, config, config.projects[0].id, "AN-02", now=NOW)
        other = notebook.task(db, config, config.projects[1].id, "AN-02", now=NOW)
    assert item["suggested"] == 95 and other["suggested"] == 10


def test_stale_and_concurrent_edits_never_overwrite_another_human_version(config):
    pid = config.projects[0].id
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        token = notebook.task(db, config, pid, "AN-02")["expected"]

    def write(nonce, text):
        try:
            return save(config, note=text, expected=token, nonce=nonce)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(write, "a" * 32, "Texto A")
        b = pool.submit(write, "b" * 32, "Texto B")
        assert sum(v is not None for v in (a.result(), b.result())) == 1
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert len(notebook.history(db, pid, "AN-02")[0]) == 1


def test_sources_and_human_notes_are_escaped_and_get_never_runs_project_code(config):
    save(config, note='<script>alert("human")</script>')
    app = create_app(config)
    with (
        patch("digest.worker.execute", side_effect=AssertionError("GET executed worker")),
        patch("digest.util.proc.run", side_effect=AssertionError("GET executed process")),
    ):
        for path in (
            "/notebook?state=all",
            "/notebook?state=all&view=graph",
            f"/notebook/{config.projects[0].id}/AN-02",
            f"/notebook/{config.projects[0].id}/AN-07",
        ):
            page = request(app, path=path)
            assert page.status_code == 200 and "<script>alert" not in page.text
            assert "<img src=x onerror=" not in page.text
    assert "&lt;script&gt;" in request(app, path=f"/notebook/{config.projects[0].id}/AN-02").text


def test_changed_or_external_snapshot_is_not_read_as_a_project_board(config, tmp_path):
    with queue.writing(config) as db:
        row = db.execute(
            "SELECT id,payload_path FROM snapshot WHERE project_id=? AND source='kanvas' "
            "ORDER BY id DESC LIMIT 1",
            (config.projects[0].id,),
        ).fetchone()
        outside = tmp_path / "outside.json"
        outside.write_bytes(Path(row[1]).read_bytes())
        db.execute("UPDATE snapshot SET payload_path=? WHERE id=?", (str(outside), row[0]))
        assert notebook.source(db, config, config.projects[0]).tasks == {}


def test_new_creation_date_does_not_inherit_old_notes_for_reused_task_id(config):
    save(config, note="Nota de la tarea anterior", base=99)
    kanvas = _kanvas()

    def change(board):
        kanvas.find_task(board, "AN-02")["at"] = "2026-11-04T10:00:00+00:00"

    kanvas.mutate(str(Path(config.projects[0].root) / "kanvas.json"), change)
    execute(config, enqueue(config, "capture"), now=NOW + timedelta(hours=1))
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        item = notebook.task(db, config, config.projects[0].id, "AN-02", now=NOW)
        assert item["identity_changed"] and item["personal"]["note"] == ""
        assert (
            notebook.history(db, config.projects[0].id, "AN-02")[0][0]["values"]["note"]
            == "Nota de la tarea anterior"
        )


@pytest.mark.parametrize("index", [0, 1])
def test_personal_notes_inherit_all_privacy_policies_and_keep_removed_projects(
    config, tmp_path, index
):
    private = config.projects[0].model_copy(
        update={"id": "private", "root": str(tmp_path / "private"), "external_allowed": False}
    )
    config.projects.append(private)
    save(config, project_id=config.projects[index].id, note="Información privada")
    config.projects.pop()
    save(
        config,
        project_id=config.projects[index].id,
        note="Información privada ajustada",
        nonce="b" * 32,
    )
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        report = Report(
            "temporary",
            "daily",
            (NOW - timedelta(days=1)).isoformat(),
            NOW.isoformat(),
            NOW.isoformat(),
        )
        candidates, _, _ = frontier(db, config, report, task_context(db, config))
        values, scope, _ = notebook.preferences(db, config, candidates)
    assert values and "private" in scope


def test_notebook_preferences_reach_the_next_validated_plan(config, valid_llm):
    config.projects[1].external_allowed = False
    save(config, note="Comparar el control independiente", base=99)
    job = enqueue(config, "daily", params={"no_send": True})
    path = Path(execute(config, job, now=NOW + timedelta(hours=1)))
    assert path.name == "report.md"
    report = json.loads(path.with_suffix(".json").read_text())
    context = report["packages"]["plan"]["context"]
    assert context["notebook_preferences"][0]["note"] == "Comparar el control independiente"
    assert report["model_info"]["plan"]["provider"] == "internal"


def test_pagination_settings_and_invalid_priority(config):
    app = create_app(config)
    stylesheet = request(app, path="/static/app.css")
    assert stylesheet.status_code == 200 and stylesheet.headers["content-type"].startswith(
        "text/css"
    )
    assert "{%" not in stylesheet.text and "<!doctype" not in stylesheet.text.lower()
    assert request(app, path="/notebook/settings").status_code == 200
    assert request(app, path="/notebook?minimum=101").status_code == 400
    assert request(app, path="/notebook?page_number=0").status_code == 400
    assert request(app, path="/notebook/unknown/AN-02").status_code == 404
    with pytest.raises(ValueError):
        save(config, base=101)


def test_notes_remain_accessible_when_task_disappears_from_the_next_capture(config):
    save(config, "AN-04", note="Conservar esta reflexión", base=81)
    kanvas = _kanvas()

    def remove(board):
        board["tasks"] = [t for t in board["tasks"] if t["id"] != "AN-04"]

    kanvas.mutate(str(Path(config.projects[0].root) / "kanvas.json"), remove)
    execute(config, enqueue(config, "capture"), now=NOW + timedelta(hours=1))
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        item = notebook.task(db, config, config.projects[0].id, "AN-04", now=NOW)
        assert item["archived"] and not item["available"] and item["aging_bonus"] == 0
        assert item["personal"]["note"] == "Conservar esta reflexión"
    app = create_app(config)
    assert "Conservar esta reflexión" in request(app, path="/notebook?state=archived").text
    assert (
        "Conservar esta reflexión"
        in request(app, path=f"/notebook/{config.projects[0].id}/AN-04").text
    )


def test_http_settings_and_source_refresh_are_explicit_and_idempotent(config):
    async def run():
        app = create_app(config)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1",
            follow_redirects=True,
        ) as client:
            parsed = Forms()
            parsed.feed((await client.get("/notebook/settings")).text)
            values = parsed.forms[0] | {"base": "25", "daily_step": "2", "cap": "9", "enabled": "0"}
            assert (await client.post("/notebook/settings", data=values)).status_code == 200
            assert (await client.post("/notebook/settings", data=values)).status_code == 200
            parsed = Forms()
            parsed.feed((await client.get("/notebook")).text)
            refresh = parsed.forms[1]
            with patch("digest.worker.execute", side_effect=AssertionError("POST executed worker")):
                a = await client.post("/notebook/refresh", data=refresh)
                b = await client.post("/notebook/refresh", data=refresh)
                assert a.url == b.url and a.status_code == 200
        with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
            assert notebook.settings(db)[0].model_dump() == {
                "base": 25,
                "daily_step": 2,
                "cap": 9,
                "enabled": False,
            }
            assert (
                db.execute(
                    "SELECT count(*) FROM job WHERE kind='capture' AND state='queued'"
                ).fetchone()[0]
                == 1
            )

    asyncio.run(run())


def test_note_budget_omits_a_whole_note_and_never_cuts_its_meaning(config):
    save(config, "AN-02", note="A" * 4000, base=90)
    save(config, "AN-04", note="B" * 4000, base=89, nonce="b" * 32)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        report = Report(
            "temporary",
            "daily",
            (NOW - timedelta(days=1)).isoformat(),
            NOW.isoformat(),
            NOW.isoformat(),
        )
        candidates, _, _ = frontier(db, config, report, task_context(db, config))
        values, _, omitted = notebook.preferences(db, config, candidates)
    notes = [v.get("note") for v in values if "note" in v]
    assert omitted and notes == ["A" * 4000]
    assert any(v.get("note_omitted") == "package_budget" for v in values)


def test_changed_human_revision_cannot_be_displayed_as_the_original(config):
    ident = save(config)
    with queue.writing(config) as db:
        value = notebook.revision(db, ident)
        value["values"]["note"] = "Texto manipulado"
        db.execute(
            "UPDATE meta SET value=? WHERE key=?", (json.dumps(value), "nb_revision:" + ident)
        )
    with (
        closing(connect(Path(config.paths.data_dir) / "digest.db")) as db,
        pytest.raises(ValueError, match="changed"),
    ):
        notebook.task(db, config, config.projects[0].id, "AN-02")
    page = request(create_app(config), path="/notebook")
    assert page.status_code == 409 and "Texto manipulado" not in page.text


def test_missing_notebook_privacy_scope_blocks_plan_before_provider_call(
    config, tmp_path, valid_llm
):
    private = config.projects[0].model_copy(
        update={
            "id": "removed-private",
            "root": str(tmp_path / "private"),
            "external_allowed": False,
        }
    )
    config.projects.append(private)
    save(config, note="El proyecto retirado afecta esta decisión")
    config.projects.pop()
    job = enqueue(config, "daily", params={"no_send": True})
    path = Path(execute(config, job, now=NOW + timedelta(hours=1)))
    assert path.name == "draft.md"
    value = json.loads(path.with_suffix(".json").read_text())
    assert value["pending"]["plan"][0]["rule"] == "notebook_scope_missing"
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM llm_call WHERE job_id=? AND task='plan'", (job,)
            ).fetchone()[0]
            == 0
        )
