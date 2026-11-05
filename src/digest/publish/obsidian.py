"""Publish generated notes without changing any human-authored file."""

import copy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from digest.config import Config
from digest.publish.files import create, destination
from digest.report.model import Report
from digest.report.render_md import render


def publish(config: Config, report: Report, directory: Path) -> str:
    vault = Path(config.paths.obsidian_vault)
    date = datetime.fromisoformat(report.end_at).astimezone(ZoneInfo(config.timezone))
    revision = int(report.id.rsplit("_r", 1)[1])
    suffix = "" if revision == 1 else f"-r{revision}"
    folder = config.paths.obsidian_digest_dir
    if report.kind == "weekly":
        folder += "/Semanal"
        stem = date.strftime("%G-W%V")
    else:
        stem = date.strftime("%Y-%m-%d")
    note = destination(config, vault, f"{folder}/{stem}{suffix}.md")
    rendered = copy.deepcopy(report)
    for item in rendered.results:
        for figure in item.figures:
            source = (directory / figure.path).resolve()
            if not source.is_relative_to(directory.resolve()) or source.suffix != ".png":
                raise ValueError("Invalid figure")
            relative = f"figures/{report.id}/{source.name}"
            target = destination(config, vault, f"{folder}/{relative}")
            create(target, source.read_bytes())
            figure.path = relative
    create(note, render(rendered).encode())
    return str(note)
