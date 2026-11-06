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


@pytest.mark.parametrize(
    "args",
    [
        args
        for args in COMMANDS
        if args[0] not in {"doctor", "capture", "run", "enqueue", "worker", "deliver", "resume"}
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
