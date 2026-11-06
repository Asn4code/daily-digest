"""Interruptions, fixed windows and bounded retries with fake providers only."""

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from digest.config import load_config
from digest.db import connect
from digest.llm.client import Client
from digest.llm.router import Router
from digest.worker import enqueue, execute, recover, resume
from tests.fixtures.llm import fake_response
from tests.fixtures.make_projects import build_projects

NOW = datetime(2026, 11, 4, 19, tzinfo=UTC)


def test_T29_interruption_reuses_saved_nodes_and_original_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    requests = []
    interrupted = False

    def respond(request):
        nonlocal interrupted
        wire = json.loads(request.content)
        requests.append(wire)
        if len(requests) == 2 and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("synthetic interruption")
        return fake_response(request)

    client = Client(transport=httpx.MockTransport(respond))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=client)

    with patch.object(Router, "__init__", setup):
        job = enqueue(config, "daily", params={"no_send": True})
        with pytest.raises(KeyboardInterrupt):
            execute(config, job, now=NOW)
        data = Path(config.paths.data_dir)
        assert len(list((data / "nodes").rglob("*.json"))) == 1
        with closing(connect(data / "digest.db")) as db:
            state, encoded = db.execute(
                "SELECT state,params FROM job WHERE id=?", (job,)
            ).fetchone()
            assert state == "running"
            params = json.loads(encoded)
            assert len(params["nodes"]) == 1
            frozen = Path(params["inventory_path"]).read_bytes()
            original_ids = {e["id"] for e in json.loads(frozen)["report"]["evidence"]}
            result_id = db.execute("SELECT id FROM result ORDER BY id LIMIT 1").fetchone()[0]
            db.execute("UPDATE result SET review_state='closed_by_human' WHERE id=?", (result_id,))
        # Subsequent work is captured but must not extend the interrupted window.
        (Path(config.projects[0].root) / "later.md").write_text("Trabajo posterior a la ventana.")
        recover(config)
        path = Path(execute(config, job, now=NOW + timedelta(days=1)))
    value = json.loads(path.with_suffix(".json").read_text())
    assert path.name == "report.md"
    assert value["end_at"] == NOW.isoformat()
    assert {e["id"] for e in value["evidence"]} == original_ids
    assert Path(params["inventory_path"]).read_bytes() == frozen
    assert any(m.get("reused") == "true" for m in value["model_info"].values())
    assert all(w["messages"] != requests[0]["messages"] for w in requests[2:])
    with closing(connect(data / "digest.db")) as db:
        assert db.execute("SELECT state FROM job WHERE id=?", (job,)).fetchone() == ("done",)
        assert db.execute(
            "SELECT closed FROM interval WHERE id=?", (params["interval_id"],)
        ).fetchone() == (1,)
        assert db.execute(
            "SELECT review_state FROM result WHERE id=?", (result_id,)
        ).fetchone() == ("closed_by_human",)
    assert (
        next(r for r in value["results"] if r["id"] == result_id)["review_state"]
        == "closed_by_human"
    )
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_pending_windows_do_not_overlap_or_repeat_reserved_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    monkeypatch.delenv("DIGEST_FIXTURE_UNUSED_KEY", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    first = enqueue(config, "daily", params={"no_send": True})
    a = json.loads(Path(execute(config, first, now=NOW)).with_suffix(".json").read_text())
    (Path(config.projects[0].root) / "later.md").write_text("Nuevo contraste pendiente.")
    second = enqueue(config, "daily", params={"no_send": True})
    b = json.loads(
        Path(execute(config, second, now=NOW + timedelta(days=1))).with_suffix(".json").read_text()
    )
    assert a["end_at"] == b["start_at"]
    assert a["evidence"] and b["evidence"]
    assert not {e["id"] for e in a["evidence"]} & {e["id"] for e in b["evidence"]}
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT count(*) FROM interval WHERE closed=1").fetchone() == (0,)
    recover(config)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        queued = db.execute("SELECT id,params FROM job WHERE state='queued'").fetchall()
    recover(config)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT id,params FROM job WHERE state='queued'").fetchall() == queued
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_pending_attempts_are_bounded_and_explicit_resume_preserves_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    monkeypatch.delenv("DIGEST_FIXTURE_UNUSED_KEY", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    job = enqueue(config, "daily", params={"no_send": True})
    first_path = Path(execute(config, job, now=NOW))
    frozen = first_path.read_bytes()
    for attempt in range(2):
        recover(config)
        assert (
            Path(execute(config, job, now=NOW + timedelta(minutes=attempt + 1))).name == "draft.md"
        )
    recover(config)
    assert execute(config, job, now=NOW + timedelta(minutes=5)) is None
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        state, error, encoded = db.execute(
            "SELECT state,error,params FROM job WHERE id=?", (job,)
        ).fetchone()
        params = json.loads(encoded)
        assert (state, error, params["attempts"]) == ("failed", "report_pending", 3)
        assert db.execute("SELECT count(*) FROM interval WHERE closed=1").fetchone() == (0,)
    resume(config, job, no_send=True)
    path = Path(execute(config, job, now=NOW + timedelta(minutes=10)))
    assert path != first_path and first_path.read_bytes() == frozen
    value = json.loads(path.with_suffix(".json").read_text())
    assert value["start_at"] == params["since"] and value["end_at"] == params["until"]
    assert not list((Path(config.paths.data_dir) / "nodes").rglob("*.json"))
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_completed_revision_supersedes_older_pending_jobs_but_can_itself_be_regenerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_llm: None
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    monkeypatch.delenv("DIGEST_FIXTURE_UNUSED_KEY")
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    first = enqueue(config, "daily", params={"no_send": True})
    draft = Path(execute(config, first, now=NOW))
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        params = json.loads(db.execute("SELECT params FROM job WHERE id=?", (first,)).fetchone()[0])
    bounds = {"since": params["since"], "until": params["until"], "no_send": True}
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    second = enqueue(config, "daily", params=bounds)
    complete = Path(execute(config, second, now=NOW + timedelta(minutes=1)))
    assert complete.name == "report.md"
    original = complete.read_bytes()
    recover(config)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT state,error FROM job WHERE id=?", (first,)).fetchone() == (
            "skipped",
            "superseded_by_ready_report",
        )
    assert draft.exists()
    # A deliberate new revision may remain pending while the earlier completed
    # revision keeps the interval closed. It can still resume its own attempt.
    config.llm.providers["internal"].model += "-changed"
    monkeypatch.delenv("DIGEST_FIXTURE_UNUSED_KEY")
    third = enqueue(config, "daily", params=bounds)
    assert Path(execute(config, third, now=NOW + timedelta(minutes=2))).name == "draft.md"
    resume(config, third, no_send=True)
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    revised = Path(execute(config, third, now=NOW + timedelta(minutes=3)))
    assert revised.name == "report.md" and revised != complete
    assert complete.read_bytes() == original
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize("after_close", [False, True])
def test_ready_report_recovery_finishes_same_report_and_queues_delivery_once(
    tmp_path: Path, valid_llm: None, after_close: bool
) -> None:
    from digest.intervals import close_interval

    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    job = enqueue(config, "daily")

    def interrupt(db, interval_id, report_id):
        if after_close:
            close_interval(db, interval_id, report_id)
        raise KeyboardInterrupt("Synthetic interruption at publication boundary")

    with patch("digest.worker.close_interval", side_effect=interrupt):
        with pytest.raises(KeyboardInterrupt):
            execute(config, job, now=NOW)
    recover(config)
    recover(config)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert db.execute("SELECT state FROM job WHERE id=?", (job,)).fetchone() == ("done",)
        assert db.execute("SELECT closed FROM interval").fetchone() == (1,)
        reports = db.execute("SELECT id,status FROM report").fetchall()
        assert len(reports) == 1 and reports[0][1] == "ready"
        deliveries = db.execute(
            "SELECT params FROM job WHERE kind='deliver' AND state='queued'"
        ).fetchall()
        assert len(deliveries) == 1
        assert json.loads(deliveries[0][0])["report"] == reports[0][0]
        assert db.execute("SELECT count(*) FROM delivery").fetchone() == (0,)
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
