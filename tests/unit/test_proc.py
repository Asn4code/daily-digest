"""Processes must treat arguments literally and leave credentials behind."""

import ast
import json
import sys
from pathlib import Path

import pytest

from digest.util.proc import ProcessError, run


def test_T08_arguments_are_not_shell(tmp_path: Path) -> None:
    value = "spaces ' \" $(touch injected); echo bad\n"
    result = run(
        [sys.executable, "-c", "import sys; print(sys.argv[1],end='')", value],
        timeout=5,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert result.stdout == value
    assert not (tmp_path / "injected").exists()


def test_environment_is_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "do-not-inherit")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")
    result = run(
        [sys.executable, "-c", "import os,json; print(json.dumps(dict(os.environ)))"], timeout=5
    )
    env = json.loads(result.stdout)
    assert "PRIVATE_KEY" not in env
    assert "PYTHONPATH" not in env
    assert "HOME" not in env
    assert env["GIT_OPTIONAL_LOCKS"] == "0"


def test_reject_string_and_invalid_timeout() -> None:
    with pytest.raises(TypeError):
        run("echo unsafe", timeout=1)  # type: ignore[arg-type]
    for timeout in [0, -1, float("inf"), float("nan")]:
        with pytest.raises(ValueError):
            run([sys.executable], timeout=timeout)


def test_timeout_and_failure_are_explicit() -> None:
    with pytest.raises(ProcessError, match="process_timeout"):
        run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.02)
    with pytest.raises(ProcessError, match="process_unavailable"):
        run(["/nonexistent/tool"], timeout=1)
    assert run([sys.executable, "-c", "raise SystemExit(7)"], timeout=5).returncode == 7


def test_no_shell_or_process_calls_outside_wrapper() -> None:
    source = Path(__file__).resolve().parents[2] / "src"
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name != "subprocess" or path.name == "proc.py" for a in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module != "subprocess" or path.name == "proc.py"
            if isinstance(node, ast.Call):
                assert not any(
                    k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True
                    for k in node.keywords
                )
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in {"system", "popen", "getoutput", "getstatusoutput"}
