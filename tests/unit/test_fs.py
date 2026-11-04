"""Confinement, exclusions, bounded reads and deterministic race tests."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from digest.util.fs import ReadError, read_bounded, safe_path


def test_T09_symlink_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("private")
    (root / "link").symlink_to(outside)
    for path in ["link", "../outside", str(outside)]:
        with pytest.raises(ReadError, match="outside_root"):
            read_bounded(root, path)


def test_internal_link_and_unusual_names(tmp_path: Path) -> None:
    name = "space ' \" $(touch marker)\n.md"
    (tmp_path / name).write_bytes(b"data")
    (tmp_path / "link").symlink_to(name)
    assert read_bounded(tmp_path, name) == b"data"
    assert read_bounded(tmp_path, "link") == b"data"
    assert not (tmp_path / "marker").exists()


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.local",
        "private.key",
        "id_rsa",
        ".git/config",
        ".venv/a",
        "file.xtc",
        "file.mrc",
    ],
)
def test_excluded_without_opening(tmp_path: Path, name: str) -> None:
    with patch("digest.util.fs.os.open", side_effect=AssertionError("must not open")):
        with pytest.raises(ReadError, match="excluded"):
            read_bounded(tmp_path, name)


def test_alias_cannot_bypass_exclusions(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("private")
    (tmp_path / "public").symlink_to(".env")
    with pytest.raises(ReadError, match="excluded"):
        read_bounded(tmp_path, "public")
    (tmp_path / "report.md").write_text("data")
    with pytest.raises(ReadError, match="excluded"):
        safe_path(tmp_path, "report.md", exclude=["**/*.md"])


def test_T10_large_file_never_read(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    with path.open("wb") as stream:
        stream.truncate(3_000_000_000)
    with patch("digest.util.fs.os.open", side_effect=AssertionError("must not open")):
        with pytest.raises(ReadError, match="too_large"):
            read_bounded(tmp_path, "large.bin")
    path.rename(tmp_path / "large.xtc")
    with pytest.raises(ReadError, match="excluded"):
        read_bounded(tmp_path, "large.xtc")


def test_T07_changed_during_read(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_bytes(b"old")
    original = os.read

    def changing_read(fd: int, size: int) -> bytes:
        value = original(fd, size)
        if value:
            path.write_bytes(b"new content")
        return value

    with patch("digest.util.fs.os.read", side_effect=changing_read):
        with pytest.raises(ReadError, match="changed_during_read"):
            read_bounded(tmp_path, path.name)


def test_replaced_with_symlink_before_open(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("original")
    original = safe_path

    def replacing(root: Path, relative: str | Path, **kwargs: object) -> Path:
        checked = original(root, relative)
        path.unlink()
        path.symlink_to("/etc/passwd")
        return checked

    with patch("digest.util.fs.safe_path", side_effect=replacing):
        with pytest.raises(ReadError):
            read_bounded(tmp_path, path.name)


def test_loop_fifo_and_boundary(tmp_path: Path) -> None:
    (tmp_path / "loop").symlink_to("loop")
    os.mkfifo(tmp_path / "fifo")
    for name in ["loop", "fifo"]:
        with pytest.raises(ReadError):
            read_bounded(tmp_path, name)
    (tmp_path / "file").write_bytes(b"1234")
    assert read_bounded(tmp_path, "file", max_bytes=4) == b"1234"
    with pytest.raises(ReadError, match="too_large"):
        read_bounded(tmp_path, "file", max_bytes=3)
