"""Immutable copies to the configured remote, without sharing or deleting."""

import json
from pathlib import Path
from urllib.parse import quote

from digest.config import Config
from digest.report.model import Report
from digest.util.proc import run


def publish(config: Config, report: Report, directory: Path) -> str:
    remote = config.drive.remote.rstrip("/") + "/reports/" + report.kind + "/" + report.id
    args = ["rclone"]
    if remote.startswith(":local:"):
        args += ["--config", "/dev/null"]
    result = run(
        [
            *args,
            "copy",
            "--immutable",
            "--retries",
            "1",
            "--low-level-retries",
            "1",
            str(directory),
            remote,
        ],
        timeout=300,
    )
    if result.returncode:
        raise RuntimeError("Drive copy failed")
    return remote


def url(config: Config, remote: str) -> str | None:
    if remote.startswith(":local:"):
        return None
    result = run(["rclone", "lsjson", "--stat", remote], timeout=20)
    if result.returncode:
        return None
    try:
        item = json.loads(result.stdout)
        ident = item.get("ID")
        if not isinstance(ident, str) or not ident:
            return None
        return "https://drive.google.com/drive/folders/" + quote(ident, safe="")
    except (ValueError, AttributeError):
        return None
