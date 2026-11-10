"""Read-only web screens and adversarial requests, without sockets or real services."""

import asyncio
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from digest.config import load_config
from digest.db import connect
from digest.llm.client import Client
from digest.llm.router import Router
from digest.report.loading import load_ready
from digest.report.model import EvidenceEntry
from digest.report.observations import normalize
from digest.web.app import create_app
from digest.worker import enqueue, execute
from tests.fixtures.llm import fake_response
from tests.fixtures.make_projects import build_projects
from tests.fixtures.work import add_current_work


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    root = tmp_path_factory.mktemp("web")
    config = load_config(build_projects(root / "projects"))
    config.projects = config.projects[:1]
    config.projects[0].name = "Proyecto <script>alert('title')</script>"
    add_current_work(config)
    client = Client(transport=httpx.MockTransport(fake_response))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=client)

    with pytest.MonkeyPatch.context() as env, patch.object(Router, "__init__", setup):
        env.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
        job = enqueue(config, "daily", params={"no_send": True})
        path = Path(execute(config, job, now=datetime(2026, 11, 4, 19, tzinfo=UTC)))
        weekly = enqueue(config, "weekly", params={"no_send": True})
        execute(config, weekly, now=datetime(2026, 11, 7, 9, tzinfo=UTC))
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        ident = json.loads(path.with_suffix(".json").read_text())["id"]
        document, file, _ = load_ready(db, config, ident)
        raw = file.read_bytes()
    yield config, document, file, raw
    (root / "projects/proj-fail/no-access").chmod(0o700)


def request(app, method="GET", path="/", *, peer="127.0.0.1", headers=None):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=(peer, 50000)),
            base_url="http://127.0.0.1",
            follow_redirects=True,
        ) as client:
            return await client.request(method, path, headers=headers)

    return asyncio.run(run())


def test_today_detail_history_and_pwa_are_local_read_only(sample):
    config, report, file, raw = sample
    app = create_app(config)
    db_path = Path(config.paths.data_dir) / "digest.db"
    with closing(sqlite3.connect(db_path)) as db:
        before = {
            t: db.execute("SELECT * FROM " + t).fetchall()
            for t in ("result", "review", "plan_item", "job")
        }
    page = request(app)
    assert page.status_code == 200
    assert page.url.path == "/reports/" + report.id
    assert "Lo que merece tu atención" in page.text
    assert all(r.title in page.text for r in report.results)
    assert "Antes de interpretar" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"
    for result in report.results:
        detail = request(app, path=f"/reports/{report.id}/results/{result.id}")
        assert detail.status_code == 200 and result.title in detail.text
    history = request(app, path="/history?q=contrastar")
    assert history.status_code == 200 and report.id in history.text
    assert request(app, path="/r/2026-11-04").url.path == "/reports/" + report.id
    manifest = request(app, path="/manifest.webmanifest").json()
    assert manifest["display"] == "standalone"
    assert request(app, path=manifest["icons"][0]["src"]).content.startswith(b"\x89PNG")
    assert request(app, path="/static/app.js").status_code == 200
    assert request(app, path="/healthz").json() == {"status": "ok", "database": "ok"}
    assert file.read_bytes() == raw
    with closing(sqlite3.connect(db_path)) as db:
        assert {t: db.execute("SELECT * FROM " + t).fetchall() for t in before} == before


def test_T19_wrong_identity_or_nonlocal_peer_is_forbidden(sample):
    config, report, _, _ = sample
    app = create_app(config)
    assert (
        request(app, headers={"Tailscale-User-Login": "someone-else@example.test"}).status_code
        == 403
    )
    assert (
        request(
            app, headers={"Tailscale-User-Login": config.web.allowed_tailscale_login}
        ).status_code
        == 200
    )
    assert (
        request(
            app,
            peer="10.0.0.2",
            headers={"Tailscale-User-Login": config.web.allowed_tailscale_login},
        ).status_code
        == 403
    )
    assert request(app, headers={"Host": "127.0.0.1.evil.test"}).status_code == 400
    assert request(app, headers={"Host": "127.0.0.1/path"}).status_code == 400
    assert (
        request(
            app,
            headers=[
                ("Tailscale-User-Login", config.web.allowed_tailscale_login),
                ("Tailscale-User-Login", config.web.allowed_tailscale_login),
            ],
        ).status_code
        == 403
    )


def test_weekly_uses_validated_report_with_review_status_and_patterns(sample):
    app = create_app(sample[0])
    response = request(app, path="/w/2026-W45")
    assert response.status_code == 200
    assert "Una mirada a la semana" in response.text
    assert "Revisiones recogidas en el semanal" in response.text
    assert "Patrones observados" in response.text
    assert request(app, path="/week").url.path == response.url.path


def test_T20_csrf_is_signed_session_bound_and_body_bounded(sample):
    from starlette.responses import PlainTextResponse

    config, _, _, _ = sample
    app = create_app(config)
    reached = []

    @app.post("/test-action")
    def action():
        reached.append(True)
        return PlainTextResponse("done")

    async def run():
        transport = httpx.ASGITransport(app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as a:
            assert (await a.post("/test-action")).status_code == 403
            page = await a.get("/")
            if page.status_code == 303:
                page = await a.get(page.headers["location"])
            token = re.search(r'name="csrf-token" content="([a-f0-9]+)"', page.text).group(1)
            assert "HttpOnly" in page.headers.get("set-cookie", "") or a.cookies
            assert (await a.post("/test-action", data={"csrf_token": "a" * 64})).status_code == 403
            assert (
                await a.post(
                    "/test-action",
                    data={"csrf_token": token},
                    headers={"Origin": "https://evil.test"},
                )
            ).status_code == 403
            assert (
                await a.post("/test-action", content=b"x" * 64001, headers={"X-CSRF-Token": token})
            ).status_code == 413
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as b:
                await b.get("/")
                assert (await b.post("/test-action", data={"csrf_token": token})).status_code == 403
            assert (await a.post("/test-action", data={"csrf_token": token})).status_code == 200

    asyncio.run(run())
    assert reached == [True]


@pytest.mark.parametrize(
    "path",
    [
        "/reports/unknown",
        "/r/2000-01-01",
        "/w/2026-W00",
        "/reports/../../config.yaml",
        "/static/../app.py",
        "/static/.env",
        "/reports/x/figures/%2e%2e.png",
        "/reports/x/results/unknown",
        "/history?page_number=-1",
        "/history?q=" + "a" * 201,
    ],
)
def test_unknown_paths_and_unbounded_search_are_rejected(sample, path):
    assert request(create_app(sample[0]), path=path).status_code in {400, 404}


def test_T14_source_markup_is_escaped_and_invalid_llm_never_served(sample):
    config, report, file, raw = sample
    app = create_app(config)
    malicious = "<script>alert('note')</script><img src=x onerror=alert('event')>"
    changed = deepcopy(report)
    extra = EvidenceEntry(
        "ev_web_xss",
        config.projects[0].id,
        "task_note",
        "kanvas.json#note",
        malicious,
        report.end_at,
        report.end_at,
        "event",
        {},
        content_hash=hashlib.sha256(malicious.encode()).hexdigest(),
        context_only=True,
    )
    changed.evidence.append(extra)
    changed.observations[extra.id] = normalize(extra)
    db_path = Path(config.paths.data_dir) / "digest.db"
    with closing(connect(db_path)) as db:
        db.execute(
            "INSERT INTO evidence(id,project_id,source,kind,locator,observed_at,event_at,"
            "time_quality,content_hash,excerpt,meta) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                extra.id,
                extra.project,
                "kanvas",
                extra.kind,
                extra.locator,
                extra.observed_at,
                extra.event_at,
                extra.time_quality,
                extra.content_hash,
                extra.excerpt,
                "{}",
            ),
        )
        db.execute("INSERT INTO report_evidence VALUES (?,?)", (report.id, extra.id))
    try:
        file.write_text(json.dumps(asdict(changed)))
        page = request(app, path="/reports/" + report.id)
        assert page.status_code == 200
        assert "<script>alert" not in page.text and "&lt;script&gt;" in page.text
        assert "&lt;img src=x onerror=" in page.text
        assert "<script>alert('title')" not in page.text
        changed.sections["conceptual"]["highlights"][0]["observation"]["text"] = malicious
        file.write_text(json.dumps(asdict(changed)))
        assert request(app, path="/reports/" + report.id).status_code == 404
    finally:
        file.write_bytes(raw)
        with closing(connect(db_path)) as db:
            db.execute(
                "DELETE FROM report_evidence WHERE report_id=? AND evidence_id=?",
                (report.id, extra.id),
            )
            db.execute("DELETE FROM evidence WHERE id=?", (extra.id,))


def test_only_report_directory_and_generated_png_are_served(sample, tmp_path):
    config, report, file, raw = sample
    secret = tmp_path / "secret.json"
    secret.write_bytes(raw)
    db_path = Path(config.paths.data_dir) / "digest.db"
    with closing(connect(db_path)) as db:
        before = db.execute("SELECT json_path FROM report WHERE id=?", (report.id,)).fetchone()[0]
        db.execute("UPDATE report SET json_path=? WHERE id=?", (str(secret), report.id))
    try:
        assert request(create_app(config), path="/reports/" + report.id).status_code == 404
    finally:
        with closing(connect(db_path)) as db:
            db.execute("UPDATE report SET json_path=? WHERE id=?", (before, report.id))
    app = create_app(config)
    figures = [f for r in report.results for f in r.figures]
    assert figures
    image = request(app, path=f"/reports/{report.id}/figures/{figures[0].evidence}.png")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert request(app, path=f"/reports/{report.id}/figures/unknown.png").status_code == 404


def test_empty_installation_does_not_create_a_database(sample, tmp_path):
    config = sample[0].model_copy(deep=True)
    config.paths.data_dir = str(tmp_path / "new-data")
    page = request(create_app(config))
    assert page.status_code == 200 and "Todavía no hay" in page.text
    health = request(create_app(config), path="/healthz")
    assert health.status_code == 503
    assert health.json() == {"status": "degraded", "database": "unavailable"}
    assert not Path(config.paths.data_dir).exists()


def test_corrupt_database_health_is_generic_and_read_only(sample, tmp_path):
    config = sample[0].model_copy(deep=True)
    config.paths.data_dir = str(tmp_path)
    path = tmp_path / "digest.db"
    raw = b"private corrupt database content"
    path.write_bytes(raw)
    health = request(create_app(config), path="/healthz")
    assert health.status_code == 503 and "private" not in health.text
    assert path.read_bytes() == raw
