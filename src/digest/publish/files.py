"""Immutable, atomic publication to service-owned or designated output folders."""

import os
import tempfile
from pathlib import Path

from digest.config import Config


def destination(config: Config, base: Path, relative: str) -> Path:
    root = base.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Output escapes destination")
    if any(target.is_relative_to(Path(p.root).resolve()) for p in config.projects):
        raise ValueError("Output overlaps observed project")
    return target


def create(path: Path, raw: bytes) -> None:
    """Expose complete bytes atomically; an existing different file is a conflict."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise FileExistsError("Immutable output conflict")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".digest-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != raw:
            raise FileExistsError("Immutable output conflict") from None
    finally:
        temporary.unlink(missing_ok=True)
