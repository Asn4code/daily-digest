"""Check public CLI discovery and honest failure for unfinished operations."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from digest.cli import app

runner = CliRunner()
COMMANDS = [
    ["doctor"],
    ["capture", "--project", "demo"],
    ["run", "--now", "--no-send"],
    ["run", "--weekly"],
    ["run", "--preview"],
    ["enqueue", "daily", "--requested-by", "timer"],
    ["worker"],
    ["resume", "1", "--now", "--no-send"],
    ["web"],
    ["deliver", "--retry", "--channel", "email", "--force-uncertain"],
    ["backup"],
    ["restore", "--from", "copy"],
    ["brief", "teaching", "res_demo", "--zip"],
    ["extensions"],
    ["mcp"],
]


def test_help_lists_documented_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for args in COMMANDS:
        assert args[0] in result.output


@pytest.mark.parametrize("command", sorted({args[0] for args in COMMANDS}))
def test_command_help(command: str) -> None:
    assert runner.invoke(app, [command, "--help"]).exit_code == 0


def test_web_cli_uses_local_bind_without_proxy_trust_or_query_logging(tmp_path, monkeypatch):
    from tests.fixtures.make_projects import build_projects

    path = build_projects(tmp_path / "projects")
    called = []
    monkeypatch.setattr("uvicorn.run", lambda application, **kwargs: called.append(kwargs))
    try:
        result = runner.invoke(app, ["--config", str(path), "web"])
        assert result.exit_code == 0, result.output
        assert called == [
            {"host": "127.0.0.1", "port": 8090, "proxy_headers": False, "access_log": False}
        ]
    finally:
        (path.parent / "proj-fail/no-access").chmod(0o700)


@pytest.mark.parametrize(
    "args",
    [
        args
        for args in COMMANDS
        if args[0]
        not in {"doctor", "capture", "run", "enqueue", "worker", "deliver", "resume", "web"}
    ],
)
def test_unimplemented_commands_fail_without_writing(
    args: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.rglob("*"))
    result = runner.invoke(app, ["--config", "missing.yaml", *args])
    assert result.exit_code == 1
    assert "pendiente de implementación" in result.output
    assert set(tmp_path.rglob("*")) == before
