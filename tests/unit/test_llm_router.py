"""Exercise provider failures, repair, metadata audit and privacy without network."""

import json
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from digest.config import load_config
from digest.db import connect
from digest.llm.client import Client
from digest.llm.router import Router
from tests.fixtures.doubles import FakeLLM
from tests.fixtures.make_projects import build_projects


def test_T15_preferred_provider_down_uses_fallback_with_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    for provider in config.llm.providers.values():
        monkeypatch.setenv(provider.api_key_env, "synthetic-key")
    requests = []
    fake = FakeLLM()
    package = {
        "result_id": "res_test",
        "evidence": [{"id": "ev_test", "excerpt": "Control válido"}],
    }

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if json.loads(request.content)["model"] == config.llm.providers["internal"].model:
            return httpx.Response(503, text="PRIVATE_HTTP_BODY")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": fake.generate(package)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(
            db, config, client=Client(transport=httpx.MockTransport(respond), sleep=lambda _: None)
        )
        answer = router.generate(
            "extract",
            project_ids={config.projects[0].id},
            prompt_name="extract",
            prompt_version="1",
            messages=[{"role": "user", "content": "bounded"}],
            schema={"type": "object"},
            validate=lambda value: value,
        )
        assert answer is not None and answer.provider == "nan"
        assert len(requests) == 4
        rows = db.execute(
            "SELECT provider,model,prompt_version,ok,error,input_tokens FROM llm_call"
        ).fetchall()
        assert [r[3] for r in rows] == [0, 0, 0, 1]
        assert rows[-1][0] == "nan" and rows[-1][2] == "1" and rows[-1][5] == 10
        assert "PRIVATE_HTTP_BODY" not in repr(rows) and "synthetic-key" not in repr(rows)
        assert json.loads(requests[-1].content)["response_format"]["type"] == "json_schema"
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_T16_both_providers_down_returns_mechanical_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    for p in config.llm.providers.values():
        monkeypatch.setenv(p.api_key_env, "synthetic-key")
    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(
            db,
            config,
            client=Client(
                transport=httpx.MockTransport(lambda _: httpx.Response(503)), sleep=lambda _: None
            ),
        )
        assert (
            router.generate(
                "extract",
                project_ids={config.projects[0].id},
                prompt_name="extract",
                prompt_version="1",
                messages=[],
                schema=None,
                validate=lambda value: value,
            )
            is None
        )
        assert db.execute("SELECT count(*) FROM llm_call WHERE ok=0").fetchone()[0] == 6
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_private_project_never_reaches_external_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    config.projects[0].external_allowed = False
    for p in config.llm.providers.values():
        monkeypatch.setenv(p.api_key_env, "synthetic-key")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(401, text="PRIVATE_SECRET")

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        assert (
            router.generate(
                "conceptual",
                project_ids={config.projects[0].id},
                prompt_name="conceptual",
                prompt_version="1",
                messages=[],
                schema=None,
                validate=lambda value: value,
            )
            is None
        )
        assert len(requests) == 1
        assert db.execute("SELECT DISTINCT provider FROM llm_call").fetchall() == [("internal",)]
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_broken_json_gets_one_repair_and_no_raw_error_in_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    monkeypatch.setenv(config.llm.providers["internal"].api_key_env, "synthetic-key")
    fake = FakeLLM("broken_json")
    package = {"result_id": "res_test", "evidence": []}
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": fake.generate(package)}}]}
        )

    with closing(connect(tmp_path / "db.sqlite")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        assert (
            router.generate(
                "extract",
                project_ids={config.projects[0].id},
                prompt_name="extract",
                prompt_version="1",
                messages=[],
                schema=None,
                validate=lambda value: value,
            )
            is not None
        )
        assert len(requests) == 2
        assert len(json.loads(requests[1].content)["messages"]) == 1
        assert db.execute("SELECT ok,error FROM llm_call").fetchall() == [
            (0, "invalid_json"),
            (1, None),
        ]
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
