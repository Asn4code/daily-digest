"""Web requests only enqueue; serialized workers deliver through local doubles."""

import asyncio
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from digest import queue, worker
from digest.db import connect
from digest.web.app import create_app
from tests.e2e.test_web_reading import request
from tests.fixtures.doubles import LocalSMTP
from tests.integration.test_publication import NOW
from tests.integration.test_publication import config as config


def web_request(app, kind="daily"):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1",
            follow_redirects=True,
        ) as client:
            page = await client.get("/generate")
            csrf = re.search(r'name="csrf-token" content="([a-f0-9]+)"', page.text)[1]
            nonce = re.search(r'name="submission_id" value="([a-f0-9]+)"', page.text)[1]
            data = {"csrf_token": csrf, "submission_id": nonce, "kind": kind}
            response = await client.post("/generate", data=data)
            repeated = await client.post("/generate", data=data)
            assert repeated.url == response.url
            assert response.status_code == 200
            return int(response.url.path.rsplit("/", 1)[1])

    return asyncio.run(run())


def test_generate_get_is_read_only_and_post_never_executes_a_worker(config):
    app = create_app(config)
    assert request(app, path="/generate").status_code == 200
    assert not (Path(config.paths.data_dir) / "digest.db").exists()
    with (
        patch("digest.worker.execute", side_effect=AssertionError("Web executed worker")),
        patch("digest.capture.capture", side_effect=AssertionError("Web captured a project")),
        patch(
            "digest.llm.client.Client.complete", side_effect=AssertionError("Web called a provider")
        ),
    ):
        job = web_request(app)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT id,state FROM job").fetchall() == [(job, "queued")]
        assert db.execute("SELECT count(*) FROM report").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 0


def test_T03_mobile_manual_then_timer_delivers_once_without_new_evidence(config):
    app = create_app(config)
    with LocalSMTP() as server, patch("smtplib.SMTP.starttls"), patch("smtplib.SMTP.login"):
        config.email.smtp_port = server.port
        job = web_request(app)
        output = worker.execute(config, job, now=NOW)
        assert Path(output).name == "report.md"
        assert len(server.messages) == 1
        timer = worker.enqueue(config, "daily", requested_by="timer")
        assert worker.execute(config, timer, now=NOW + timedelta(minutes=10)) == "skipped"
        assert len(server.messages) == 1
    page = request(app, path=f"/jobs/{job}")
    assert "Abrir diario validado" in page.text and "Entregado" in page.text
    assert "reintentar" not in page.text.lower()
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT count(*) FROM report WHERE status='ready'").fetchone()[0] == 1
        assert db.execute("SELECT state FROM job WHERE id=?", (timer,)).fetchone()[0] == "skipped"


def test_T04_concurrent_button_and_timer_share_a_job_and_workers_serialize(config):
    with queue.writing(config):
        pass
    app = create_app(config)
    with ThreadPoolExecutor(max_workers=2) as pool:
        button = pool.submit(web_request, app)
        timer = pool.submit(worker.enqueue, config, "daily", requested_by="timer")
        job = button.result(timeout=10)
        assert timer.result(timeout=10) == job
    entered, release, attempted, finished = (threading.Event() for _ in range(4))
    original = worker.capture
    original_lock = worker.lock
    attempts = []

    @contextmanager
    def observed_lock(cfg):
        attempts.append(True)
        if len(attempts) == 2:
            attempted.set()
        with original_lock(cfg) as db:
            yield db

    def capture(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    with (
        LocalSMTP() as server,
        patch("smtplib.SMTP.starttls"),
        patch("smtplib.SMTP.login"),
        patch.object(worker, "capture", capture),
        patch.object(worker, "lock", observed_lock),
    ):
        config.email.smtp_port = server.port
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(worker.execute, config, job, now=NOW)
            assert entered.wait(5)
            second = pool.submit(worker.execute, config, job, now=NOW)
            second.add_done_callback(lambda _: finished.set())
            assert attempted.wait(5)
            assert not finished.wait(0.2)
            release.set()
            assert Path(first.result(timeout=20)).name == "report.md"
            assert second.result(timeout=20) is None
        assert len(server.messages) == 1
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT count(*) FROM job").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM report").fetchone()[0] == 1


def test_preview_does_not_deliver_or_close_and_weekly_uses_its_own_queue(config):
    app = create_app(config)
    preview = web_request(app, "preview")
    output = Path(worker.execute(config, preview, now=NOW))
    assert output.name == "report.md"
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT closed FROM interval").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM delivery").fetchone()[0] == 0
    weekly = web_request(app, "weekly")
    assert weekly != preview
    assert "Semanal" in request(app, path=f"/jobs/{weekly}").text


def test_only_one_failed_channel_is_queued_and_uncertain_or_sent_are_rejected(config):
    job = worker.enqueue(config, "daily", params={"no_send": True})
    path = Path(worker.execute(config, job, now=NOW))
    ident = json.loads(path.with_suffix(".json").read_text())["id"]
    with queue.writing(config) as db:
        for channel, state in (("email", "uncertain"), ("drive", "failed"), ("obsidian", "sent")):
            db.execute(
                "INSERT INTO delivery(report_id,channel,state,updated_at) VALUES (?,?,?,?)",
                (ident, channel, state, NOW.isoformat()),
            )
        rows = {r[0]: r[1] for r in db.execute("SELECT channel,id FROM delivery")}
        retry = queue.retry_delivery(db, rows["drive"], "a" * 32)
        assert queue.retry_delivery(db, rows["drive"], "b" * 32) == retry
    for channel in ("email", "obsidian"):
        with pytest.raises(ValueError), queue.writing(config) as db:
            queue.retry_delivery(db, rows[channel], "c" * 32)
    with (
        patch("digest.publish.email.send", side_effect=AssertionError("Uncertain email replayed")),
        patch(
            "digest.publish.obsidian.publish",
            side_effect=AssertionError("Successful vault repeated"),
        ),
    ):
        worker.execute(config, retry, now=NOW)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute(
            "SELECT state,attempts FROM delivery WHERE channel='email'"
        ).fetchone() == ("uncertain", 0)
        assert (
            db.execute("SELECT state FROM delivery WHERE channel='drive'").fetchone()[0] == "sent"
        )
    page = request(create_app(config), path=f"/jobs/{job}")
    assert "Envío incierto" in page.text
    assert f'action="/deliveries/{rows["email"]}/retry"' not in page.text


def test_raw_job_params_errors_and_unvalidated_model_text_are_never_served(config):
    job = worker.enqueue(config, "daily")
    with queue.writing(config) as db:
        db.execute(
            "UPDATE job SET params=?,error=?,state='failed' WHERE id=?",
            (
                json.dumps(
                    {"api_key": "PRIVATE_PARAMETER_MARKER", "draft_path": "/PRIVATE_PATH_MARKER"}
                ),
                "PRIVATE_ERROR_MARKER",
                job,
            ),
        )
    app = create_app(config)
    for path in ("/generate", "/generate/status", f"/jobs/{job}", f"/jobs/{job}/status"):
        page = request(app, path=path)
        assert page.status_code == 200
        assert "PRIVATE_" not in page.text


def test_queue_bounds_unknown_jobs_and_invalid_kinds(config):
    app = create_app(config)
    assert request(app, path="/generate?page_number=0").status_code == 400
    assert request(app, path="/jobs/9999").status_code == 404
    with queue.writing(config) as db, pytest.raises(ValueError):
        queue.generate(db, "backup", "a" * 32)


def test_pending_report_can_resume_without_changing_its_frozen_inventory(config, monkeypatch):
    monkeypatch.delenv("DIGEST_FIXTURE_UNUSED_KEY", raising=False)
    job = worker.enqueue(config, "daily", params={"no_send": True})
    draft = Path(worker.execute(config, job, now=NOW))
    assert draft.name == "draft.md"
    with queue.writing(config) as db:
        before = json.loads(db.execute("SELECT params FROM job WHERE id=?", (job,)).fetchone()[0])
        assert queue.resume(db, job, "a" * 32) == job
        assert queue.resume(db, job, "a" * 32) == job
        after = json.loads(db.execute("SELECT params FROM job WHERE id=?", (job,)).fetchone()[0])
    assert after["inventory_hash"] == before["inventory_hash"]
    assert (after["since"], after["until"]) == (before["since"], before["until"])
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    assert Path(worker.execute(config, job, now=NOW)).name == "report.md"


def test_explicit_revisions_and_no_send_do_not_merge_with_sending_requests(config):
    a = worker.enqueue(config, "daily", params={"no_send": True})
    b = worker.enqueue(config, "daily")
    assert a != b
    bounds = {"since": NOW.replace(hour=0).isoformat(), "until": NOW.isoformat()}
    assert worker.enqueue(config, "daily", params=bounds) != worker.enqueue(
        config, "daily", params=bounds
    )


@pytest.mark.parametrize("kind", ["plan", "review"])
def test_retry_of_plan_or_review_targets_only_its_failed_channel(config, kind):
    from digest import planning
    from digest.review import records
    from digest.util.proc import ProcessResult

    generated = worker.enqueue(config, "daily", params={"no_send": True})
    path = Path(worker.execute(config, generated, now=NOW))
    rid = json.loads(path.with_suffix(".json").read_text())["id"]
    with queue.writing(config) as db:
        report = records.document(db, config, rid)
        if kind == "plan":
            item = planning.items(db, report)[0]
            ident = planning.decide(
                db,
                config,
                rid,
                item["id"],
                "accept",
                {k: item[k] or "" for k in ("action", "done_criterion", "dependency")},
                planning.token(db, config, report),
                "a" * 32,
            )
        else:
            ident = records.submit(
                db, config, rid, report.results[0].id, "minimal", {"doubt": "Qué control falta"}
            )
        job = db.execute("SELECT max(id) FROM job WHERE kind='deliver'").fetchone()[0]
    target = "digest.publish.plan.run" if kind == "plan" else "digest.util.proc.run"
    with patch(target, return_value=ProcessResult(1, "", "")):
        worker.execute(config, job, now=NOW)
    assert "No completado" in request(create_app(config), path=f"/jobs/{job}").text
    with queue.writing(config) as db:
        if kind == "plan":
            retry = queue.retry_plan(db, config, ident, "drive", "b" * 32)
        else:
            delivery = db.execute(
                "SELECT id FROM delivery WHERE review_id=? AND channel='drive'", (ident,)
            ).fetchone()[0]
            retry = queue.retry_delivery(db, delivery, "b" * 32)
        params = json.loads(db.execute("SELECT params FROM job WHERE id=?", (retry,)).fetchone()[0])
        assert params["channel"] == "drive"
    worker.execute(config, retry, now=NOW)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        if kind == "plan":
            assert planning.meta(db, f"plan_delivery:{ident}:obsidian")["attempts"] == 1
            assert planning.meta(db, f"plan_delivery:{ident}:drive")["attempts"] == 2
        else:
            assert (
                db.execute(
                    "SELECT attempts FROM delivery WHERE review_id=? AND channel='obsidian'",
                    (ident,),
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT attempts FROM delivery WHERE review_id=? AND channel='drive'", (ident,)
                ).fetchone()[0]
                == 2
            )


def test_queue_database_symlink_cannot_write_into_a_project(config):
    target = Path(config.projects[0].root) / "keep.db"
    target.write_bytes(b"Project content")
    data = Path(config.paths.data_dir)
    data.mkdir(exist_ok=True)
    (data / "digest.db").symlink_to(target)
    with pytest.raises(ValueError):
        worker.enqueue(config, "daily")
    assert target.read_bytes() == b"Project content"


def test_delivery_without_a_target_cannot_turn_into_a_global_retry(config):
    with queue.writing(config) as db:
        ident = db.execute(
            "INSERT INTO delivery(channel,state,updated_at) VALUES ('drive','failed',?)",
            (NOW.isoformat(),),
        ).lastrowid
        with pytest.raises(ValueError, match="no target"):
            queue.retry_delivery(db, ident, "a" * 32)
        assert db.execute("SELECT count(*) FROM job").fetchone()[0] == 0
