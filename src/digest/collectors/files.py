"""Bounded file discovery shared by project collectors."""

import fnmatch
import os
from pathlib import Path

from digest.collectors.base import CaptureContext, Omission
from digest.config import ProjectConfig
from digest.util.fs import _excluded


def matches(name: str, patterns: list[str]) -> bool:
    return any(
        fnmatch.fnmatchcase(name, pattern)
        or Path(name).match(pattern)
        or (pattern.startswith("**/") and fnmatch.fnmatchcase(name, pattern[3:]))
        for pattern in patterns
    )


def discover(
    project: ProjectConfig, ctx: CaptureContext, patterns: list[str]
) -> tuple[list[str], list[Omission]]:
    root = Path(project.root)
    found: list[str] = []
    omitted: list[Omission] = []
    pending = [root]
    count = 0
    while pending:
        folder = pending.pop()
        try:
            ctx.remaining()
            with os.scandir(folder) as entries:
                for entry in entries:
                    ctx.remaining()
                    count += 1
                    if count > 100000:
                        return sorted(found), omitted + [Omission("project", "scan_limit")]
                    relative = Path(entry.path).relative_to(root)
                    if _excluded(relative, project.exclude):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif matches(relative.as_posix(), patterns):
                        found.append(relative.as_posix())
        except TimeoutError:
            return sorted(found), omitted + [Omission("project", "capture_timeout")]
        except OSError:
            omitted.append(Omission(folder.relative_to(root).as_posix(), "unreadable"))
    return sorted(found), omitted
