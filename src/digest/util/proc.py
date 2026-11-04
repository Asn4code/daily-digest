"""Run trusted tools with explicit arguments and a minimal environment."""

import math
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ProcessError(RuntimeError):
    """A sanitized tool failure that omits arguments and captured output."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


def run(args: list[str], *, timeout: float, cwd: Path | None = None) -> ProcessResult:
    """Run without shell, inherited credentials, prompts, or optional Git locks."""
    if not isinstance(args, list) or not args or any(not isinstance(arg, str) for arg in args):
        raise TypeError("args must be a nonempty list of strings")
    if any("\0" in arg for arg in args) or not args[0]:
        raise ValueError("invalid process arguments")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    environment = {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=environment,
            timeout=timeout,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ProcessError("process_timeout") from None
    except OSError:
        raise ProcessError("process_unavailable") from None
    return ProcessResult(result.returncode, result.stdout, result.stderr)
