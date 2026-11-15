"""Model choices remain private, reversible and stable across worker attempts."""

import asyncio
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import yaml
from pydantic import ValidationError

from digest import queue
from digest.config import ConfigError, LLMConfig, load_config
from digest.llm import settings
from digest.llm.client import Client
from digest.llm.router import Router
from digest.web.app import create_app
from digest.worker import enqueue, execute
from tests.e2e.test_plan_decisions import Forms
from tests.e2e.test_web_reading import request
from tests.fixtures.llm import fake_response
from tests.fixtures.make_projects import build_projects
from tests.fixtures.work import add_current_work
from tests.integration.test_fixtures import _snapshot

NOW = datetime(2026, 11, 4, 19, tzinfo=UTC)


@pytest.fixture
def config(tmp_path):
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects = config.projects[:1]
    yield config
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def change(config, task="plan", model="selected-plan", provider="internal", nonce=None):
    with queue.writing(config) as db:
        return settings.save(
            db,
            config,
            task,
            [settings.Choice(provider=provider, model=model)],
            settings.expected(db, config),
            nonce or secrets.token_hex(16),
        )


def forms(page):
    parsed = Forms()
    parsed.feed(page.text)
    return parsed.forms


def client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app, client=("127.0.0.1", 50000)),
        base_url="http://127.0.0.1",
        follow_redirects=False,
    )


def test_model_web_edit_persists_and_reverts_without_yaml_or_project_writes(config):
    original = config.model_dump()
    before = _snapshot(Path(config.projects[0].root), include_git=True)
    app = create_app(config)

    async def run():
        async with client(app) as browser:
            page = await browser.get("/settings/models")
            form = next(f for f in forms(page) if f["stage"] == "plan")
            form.update(
                action="save",
                order_0="1",
                model_0="plan-special",
                order_1="2",
                model_1="backup-special",
            )
            assert (await browser.post("/settings/models", data=form)).status_code == 303
            assert (await browser.post("/settings/models", data=form)).status_code == 303
            page = await browser.get("/settings/models")
            assert 'value="plan-special"' in page.text
            reset = forms(page)[0] | {"action": "reset_all"}
            assert (await browser.post("/settings/models", data=reset)).status_code == 303
            assert (await browser.get("/settings/models")).status_code == 200

    asyncio.run(run())
    assert config.model_dump() == original
    assert _snapshot(Path(config.projects[0].root), include_git=True) == before
    with queue.writing(config) as db:
        routes, _ = settings.selection(db, config)
        assert routes == settings.baseline(config)
        versions = settings.history(db)
        assert (
            len(versions) == 2 and versions[-1]["overrides"]["plan"][0]["model"] == "plan-special"
        )
        assert db.execute("SELECT count(*) FROM job").fetchone()[0] == 0


def test_model_form_requires_csrf_identity_and_local_authorization(config):
    app = create_app(config)
    assert request(app, path="/settings/models", peer="10.0.0.2").status_code == 403
    assert (
        request(
            app, path="/settings/models", headers={"Tailscale-User-Login": "stranger@example.test"}
        ).status_code
        == 403
    )

    async def run():
        async with client(app) as browser:
            page = await browser.get("/settings/models")
            form = next(f for f in forms(page) if f["stage"] == "extract") | {"action": "save"}
            bad = {k: v for k, v in form.items() if k != "csrf_token"}
            assert (await browser.post("/settings/models", data=bad)).status_code == 403
            assert (
                await browser.post(
                    "/settings/models", data=form, headers={"Origin": "https://stranger.test"}
                )
            ).status_code == 403
            assert (
                await browser.post(
                    "/settings/models", data=form, headers={"Tailscale-User-Login": "other"}
                )
            ).status_code == 403

    asyncio.run(run())
    assert not (Path(config.paths.data_dir) / "digest.db").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"order_0": "1", "order_1": "1"},
        {"order_0": "0", "order_1": "0"},
        {"order_0": "-1"},
        {"model_0": "<script>alert(1)</script>"},
        {"model_0": "x" * 201},
        {"stage": "shell"},
        {"base_url": "https://arbitrary.test"},
    ],
)
def test_model_form_rejects_invalid_or_injected_fields(config, changes):
    async def run():
        async with client(create_app(config)) as browser:
            page = await browser.get("/settings/models")
            form = next(f for f in forms(page) if f["stage"] == "extract")
            response = await browser.post(
                "/settings/models", data=form | {"action": "save"} | changes
            )
            assert response.status_code == 400
            assert "arbitrary.test" not in response.text and "alert(1)" not in response.text

    asyncio.run(run())
    assert not (Path(config.paths.data_dir) / "digest.db").exists()


def test_model_revision_stale_forms_and_nonce_reuse_cannot_overwrite(config):
    with queue.writing(config) as db:
        etag = settings.expected(db, config)
        first = settings.save(
            db,
            config,
            "plan",
            [settings.Choice(provider="internal", model="first")],
            etag,
            "a" * 32,
        )
        assert (
            settings.save(
                db,
                config,
                "plan",
                [settings.Choice(provider="internal", model="first")],
                etag,
                "a" * 32,
            )
            == first
        )
        for nonce in ["a" * 32, "b" * 32]:
            with pytest.raises(ValueError):
                settings.save(
                    db,
                    config,
                    "plan",
                    [settings.Choice(provider="internal", model="second")],
                    etag,
                    nonce,
                )
        assert len(settings.history(db)) == 1
        config.llm.providers["internal"].model = "yaml-changed"
        with pytest.raises(ValueError):
            settings.save(db, config, None, None, etag, "c" * 32)


def test_yaml_task_models_validate_and_route_different_models_with_same_provider(
    config, monkeypatch
):
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    config.llm.task_models = {
        "extract": {"internal": "Qwen/extract"},
        "plan": {"internal": "Qwen/plan"},
    }
    config.llm.routing.plan = ["internal"]
    config.llm.routing.extract = ["internal"]
    config.llm = LLMConfig.model_validate(config.llm.model_dump())
    wire = []

    def respond(request):
        wire.append(json.loads(request.content)["model"])
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    with queue.writing(config) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        kwargs = dict(
            project_ids={config.projects[0].id},
            prompt_name="test",
            prompt_version="1",
            messages=[],
            schema=None,
            validate=lambda v: v,
        )
        first = router.generate("extract", **kwargs)
        second = router.generate("plan", **kwargs)
        reused = router.generate("plan", **kwargs)
        assert first.model == "Qwen/extract" and second.model == "Qwen/plan" and reused.reused
        assert wire == ["Qwen/extract", "Qwen/plan"]
        changed = config.llm.model_dump()
        changed["task_models"]["plan"] = {"unknown": "model"}
        with pytest.raises(ValidationError):
            LLMConfig.model_validate(changed)
        changed = config.llm.model_dump()
        changed["providers"]["internal"]["model"] = "model with spaces"
        with pytest.raises(ValidationError):
            LLMConfig.model_validate(changed)
        changed = config.llm.model_dump()
        changed["routing"]["plan"] = ["internal", "internal"]
        with pytest.raises(ValidationError):
            LLMConfig.model_validate(changed)
        changed["task_models"] = {"shell": {"internal": "model"}}
        with pytest.raises(ValidationError):
            LLMConfig.model_validate(changed)


def test_freeze_survives_preferences_yaml_model_changes_and_checks_provider_identity(config):
    change(config, model="old")
    job = enqueue(config, "daily")
    with queue.writing(config) as db:
        old = settings.freeze(db, config, job)
    change(config, model="new")
    config.llm.providers["internal"].model = "new-yaml-model"
    with queue.writing(config) as db:
        again = settings.freeze(db, config, job)
        assert old.llm.task_models == again.llm.task_models
        assert again.llm.task_models["plan"]["internal"] == "old"
        assert settings.freeze(db, config, job + 1).llm.task_models["plan"]["internal"] == "new"
        config.llm.providers["internal"].base_url = "https://changed.test/v1"
        with pytest.raises(ValueError, match="provider configuration changed"):
            settings.freeze(db, config, job)


def test_worker_keeps_models_during_web_edits_and_records_actual_models(config, monkeypatch):
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    add_current_work(config)
    for task in settings.TASKS:
        change(config, task=task, model="before-" + task)
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body["model"])
        if len(calls) == 1:
            change(config, task="plan", model="after-plan")
        return fake_response(request)

    llm = Client(transport=httpx.MockTransport(respond))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=llm)

    with patch.object(Router, "__init__", setup):
        job = enqueue(config, "daily", params={"no_send": True})
        output = Path(execute(config, job, now=NOW))
    assert output.exists() and "before-plan" in calls and "after-plan" not in calls
    with queue.writing(config) as db:
        rows = db.execute("SELECT task,model FROM llm_call WHERE job_id=?", (job,)).fetchall()
        assert rows and all(model == "before-" + task for task, model in rows)
        assert settings.freeze(db, config, job).llm.task_models["plan"]["internal"] == "before-plan"
        next_job = queue.insert(db, "daily", {"no_send": True}, "web")
        assert (
            settings.freeze(db, config, next_job).llm.task_models["plan"]["internal"]
            == "after-plan"
        )


def test_external_model_preferences_never_override_project_privacy(config, monkeypatch):
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    config.projects[0].external_allowed = False
    change(config, task="plan", provider="nan", model="external-only")
    wire = []
    with queue.writing(config) as db:
        frozen = settings.freeze(db, config, 1)
        router = Router(
            db, frozen, client=Client(transport=httpx.MockTransport(lambda req: wire.append(req)))
        )
        assert (
            router.generate(
                "plan",
                project_ids={config.projects[0].id},
                prompt_name="test",
                prompt_version="1",
                messages=[],
                schema=None,
                validate=lambda v: v,
            )
            is None
        )
    assert wire == []


def test_model_form_never_displays_or_persists_credentials(config, monkeypatch):
    private = "PRIVATE_SENSITIVE_VALUE_123"
    monkeypatch.setenv(config.llm.providers["internal"].api_key_env, private)
    config.llm.providers["internal"].model = private
    app = create_app(config)
    page = request(app, path="/settings/models")
    assert page.status_code == 200 and private not in page.text
    assert config.llm.providers["internal"].base_url not in page.text
    assert config.llm.providers["internal"].api_key_env not in page.text

    async def run():
        async with client(app) as browser:
            page = await browser.get("/settings/models")
            form = next(f for f in forms(page) if f["stage"] == "plan")
            response = await browser.post(
                "/settings/models", data=form | {"action": "save", "model_0": private}
            )
            assert response.status_code == 400 and private not in response.text

    asyncio.run(run())
    assert not (Path(config.paths.data_dir) / "digest.db").exists()


def test_removed_provider_blocks_new_jobs_until_reset_and_tampering_is_rejected(config):
    change(config, provider="nan", model="chosen")
    del config.llm.providers["nan"]
    for task in settings.TASKS:
        setattr(config.llm.routing, task, ["internal"])
    with queue.writing(config) as db:
        with pytest.raises(ValueError):
            settings.freeze(db, config, 7)
        settings.save(db, config, None, None, settings.expected(db, config), "b" * 32)
        assert settings.freeze(db, config, 7).llm.routing.plan == ["internal"]
        revision = settings.metadata(db, "model_current")
        db.execute("UPDATE meta SET value='{}' WHERE key=?", ("model_revision:" + revision,))
        with pytest.raises(ValueError, match="revision changed"):
            settings.selection(db, config)


def test_model_page_get_does_not_run_commands_or_create_database(config):
    with (
        patch("digest.util.proc.run", side_effect=AssertionError("No processes")),
        patch("digest.llm.client.Client.complete", side_effect=AssertionError("No model call")),
    ):
        assert request(create_app(config), path="/settings/models").status_code == 200
    assert not (Path(config.paths.data_dir) / "digest.db").exists()


def test_interrupted_job_reuses_original_models_after_preferences_change(config, monkeypatch):
    from digest.worker import recover

    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    add_current_work(config)
    for task in settings.TASKS:
        change(config, task=task, model="original-" + task)
    calls = []

    def respond(request):
        calls.append(json.loads(request.content)["model"])
        if len(calls) == 2:
            raise KeyboardInterrupt("synthetic interruption")
        return fake_response(request)

    llm = Client(transport=httpx.MockTransport(respond))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=llm)

    with patch.object(Router, "__init__", setup):
        job = enqueue(config, "daily", params={"no_send": True})
        with pytest.raises(KeyboardInterrupt):
            execute(config, job, now=NOW)
        for task in settings.TASKS:
            change(config, task=task, model="different-" + task)
        recover(config)
        result = Path(execute(config, job, now=NOW))
    assert result.name == "report.md" and all(c.startswith("original-") for c in calls)
    assert any(
        v.get("reused") == "true"
        for v in json.loads(result.with_suffix(".json").read_text())["model_info"].values()
    )


def test_reset_one_stage_and_tampered_frozen_selection(config):
    change(config, task="extract", model="custom-extract")
    change(config, task="plan", model="custom-plan")
    with queue.writing(config) as db:
        settings.save(db, config, "plan", None, settings.expected(db, config), "f" * 32)
        selected, _ = settings.selection(db, config)
        assert selected["extract"][0].model == "custom-extract"
        assert selected["plan"] == settings.baseline(config)["plan"]
        settings.freeze(db, config, 1)
        db.execute("UPDATE meta SET value='{}' WHERE key='model_job:1'")
        with pytest.raises(ValueError, match="selection changed"):
            settings.freeze(db, config, 1)


def test_yaml_model_error_hides_untrusted_task_and_provider_keys(config, tmp_path):
    private = "PRIVATE_PASTED_CREDENTIAL_123"
    for values in [{private: {"internal": "model"}}, {"plan": {private: "bad model"}}]:
        raw = config.model_dump(by_alias=True)
        raw["llm"]["task_models"] = values
        path = tmp_path / "invalid.yaml"
        path.write_text(yaml.safe_dump(raw))
        with pytest.raises(ConfigError) as error:
            load_config(path)
        assert private not in str(error.value)
