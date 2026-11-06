"""Reuse only revalidated nodes with identical inputs, contracts and policy."""

import json
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from digest.config import load_config
from digest.db import connect
from digest.llm.client import Client
from digest.llm.router import Router
from tests.fixtures.make_projects import build_projects


def arguments(config):
    return dict(
        project_ids={config.projects[0].id},
        prompt_name="source",
        prompt_version="1",
        messages=[{"role": "user", "content": "bounded input"}],
        schema={"type": "object"},
        validate=lambda v: v,
    )


@pytest.mark.parametrize(
    "changed", ["messages", "schema", "prompt_version", "model", "privacy", "route"]
)
def test_cache_key_tracks_inputs_versions_models_and_project_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"valid":true}'}}]})

    with closing(connect(tmp_path / "db")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        args = arguments(config)
        first = router.generate("extract", **args)
        reused = router.generate("extract", **args)
        assert first and reused and reused.reused and first.cache_key == reused.cache_key
        assert len(calls) == 1
        if changed == "messages":
            args["messages"] = [{"role": "user", "content": "changed input"}]
        elif changed == "schema":
            args["schema"] = {"type": "object", "required": ["valid"]}
        elif changed == "prompt_version":
            args["prompt_version"] = "2"
        elif changed == "model":
            config.llm.providers["internal"].model += "-new"
        elif changed == "privacy":
            config.projects[0].external_allowed = False
        else:
            config.llm.routing.extract = ["nan", "internal"]
        next_answer = router.generate("extract", **args)
        assert next_answer and not next_answer.reused and next_answer.cache_key != first.cache_key
        assert len(calls) == 2
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_corrupt_cached_node_is_rejected_without_overwriting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(build_projects(tmp_path / "projects"))
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"valid":true}'}}]})

    def check(value):
        if value != {"valid": True}:
            raise ValueError("invalid")
        return value

    with closing(connect(tmp_path / "db")) as db:
        router = Router(db, config, client=Client(transport=httpx.MockTransport(respond)))
        args = {**arguments(config), "validate": check}
        assert router.generate("extract", **args)
        path = next((Path(config.paths.data_dir) / "nodes").rglob("*.json"))
        bad = json.loads(path.read_text())
        bad["value"] = {"valid": False}
        path.write_text(json.dumps(bad))
        corrupted = path.read_bytes()
        answer = router.generate("extract", **args)
        assert answer and not answer.reused and len(calls) == 2
        assert path.read_bytes() == corrupted
        assert len(list((Path(config.paths.data_dir) / "nodes").rglob("*.json"))) == 2
        # A successful piece is usable without credentials or remaining HTTP budget.
        monkeypatch.delenv("DIGEST_FIXTURE_UNUSED_KEY")
        router.deadline = 0
        assert router.generate("extract", **args).reused
        assert len(calls) == 2
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)


def test_fallback_has_reserved_time_inside_the_node_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from digest.llm.client import ClientError, Completion

    config = load_config(build_projects(tmp_path / "projects"))
    clock = [0.0]
    deadlines = []
    monkeypatch.setattr("digest.llm.router.time.monotonic", lambda: clock[0])

    class BudgetClient(Client):
        def complete(self, provider, messages, schema, *, deadline, observer):
            deadlines.append(deadline)
            if provider is config.llm.providers["internal"]:
                clock[0] = deadline
                observer(None, "provider_timeout", 10000)
                raise ClientError("provider_timeout")
            result = Completion({"valid": True}, None, None, 0)
            observer(result, None, 0)
            return result

    with closing(connect(tmp_path / "db")) as db:
        router = Router(db, config, client=BudgetClient(), deadline=100.0)
        answer = router.generate("extract", **arguments(config), deadline=20.0)
        assert answer and answer.provider == "nan"
        assert deadlines == [10.0, 20.0]
    (tmp_path / "projects/proj-fail/no-access").chmod(0o700)
