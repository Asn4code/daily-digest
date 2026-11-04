"""Read-only, bounded project access with confinement and race checks."""

import fnmatch
import os
import stat
from collections.abc import Sequence
from pathlib import Path

DEFAULT_EXCLUDES = (
    "*.xtc",
    "*.trr",
    "*.dcd",
    "*.nc",
    "*.mrc",
    "*.map",
    ".venv",
    "venv",
    "node_modules",
    "conda",
    ".git",
    "__pycache__",
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "id_*",
)


class ReadError(ValueError):
    """A stable omission reason, without file contents in diagnostics."""


def _excluded(path: Path, patterns: Sequence[str]) -> bool:
    name = path.as_posix()
    return any(
        fnmatch.fnmatchcase(part, pattern) for part in path.parts for pattern in DEFAULT_EXCLUDES
    ) or any(
        fnmatch.fnmatchcase(name, pattern)
        or path.match(pattern)
        or (pattern.startswith("**/") and fnmatch.fnmatchcase(name, pattern[3:]))
        for pattern in patterns
    )


def safe_path(
    root: Path, relative: str | Path, *, exclude: Sequence[str] = (), max_bytes: int = 2_000_000
) -> Path:
    """Resolve a regular file within root; reject traversal and exclusions first."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReadError("outside_root")
    if _excluded(relative, exclude):
        raise ReadError("excluded")
    try:
        base = root.resolve(strict=True)
        target = (base / relative).resolve(strict=True)
        if not target.is_relative_to(base):
            raise ReadError("outside_root")
        if _excluded(target.relative_to(base), exclude):
            raise ReadError("excluded")
        info = target.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ReadError("not_regular")
        if info.st_size > max_bytes:
            raise ReadError("too_large")
        return target
    except (OSError, RuntimeError):
        raise ReadError("unreadable") from None


def _fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_bounded(
    root: Path, relative: str | Path, *, exclude: Sequence[str] = (), max_bytes: int = 2_000_000
) -> bytes:
    """Read via no-follow descriptors and discard changes or replacements."""
    target = safe_path(root, relative, exclude=exclude, max_bytes=max_bytes)
    descriptors: list[int] = []
    try:
        # Walk from / so no ancestor can be replaced by a symlink after validation.
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(parent)
        for part in target.parts[1:-1]:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(parent)
        fd = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        descriptors.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ReadError("not_regular")
        if before.st_size > max_bytes:
            raise ReadError("too_large")
        chunks = []
        size = 0
        while size <= max_bytes:
            chunk = os.read(fd, min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(fd)
        named = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        if _fingerprint(before) != _fingerprint(after) or _fingerprint(after) != _fingerprint(
            named
        ):
            raise ReadError("changed_during_read")
        # Recheck original aliases as well as the opened inode after reading.
        if safe_path(root, relative, exclude=exclude, max_bytes=max_bytes) != target:
            raise ReadError("changed_during_read")
        if size > max_bytes:
            raise ReadError("too_large")
        return b"".join(chunks)
    except OSError:
        raise ReadError("unreadable") from None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
