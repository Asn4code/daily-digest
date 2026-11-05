"""Collect Git history and worktree changes without invoking project helpers."""

import fnmatch
import os
from datetime import datetime
from pathlib import Path

from digest.collectors.base import (
    CaptureContext,
    CollectorOutput,
    EvidenceDraft,
    Omission,
    canonical,
    content_hash,
    utc,
)
from digest.collectors.kanvas import event_time
from digest.config import ProjectConfig
from digest.util.fs import ReadError, _excluded, read_bounded, safe_path
from digest.util.proc import ProcessError, run


def _repository(root: Path, ctx: CaptureContext) -> Path:
    git = (root / ".git").resolve(strict=True)
    if not git.is_relative_to(root.resolve()) or not git.is_dir():
        raise ReadError("external_git_metadata")
    # Include directives and alternate object stores may escape the configured root.
    config = read_bounded(git, "config", max_bytes=ctx.limits.max_file_bytes)
    if b"[include" in config.lower():
        raise ReadError("git_config_include")
    for name in ["commondir", "objects/info/alternates"]:
        if (git / name).exists():
            raise ReadError("external_git_metadata")
    for directory, dirs, files in os.walk(git, followlinks=False):
        ctx.remaining()
        # Hooks are never invoked or read; remaining metadata paths must stay confined.
        dirs[:] = [name for name in dirs if name not in {"hooks", "logs"}]
        for name in [*dirs, *files]:
            path = Path(directory) / name
            if path.is_symlink() and not path.resolve().is_relative_to(root.resolve()):
                raise ReadError("external_git_metadata")
    return git


class GitCollector:
    source = "git"
    phase = 1

    def collect(
        self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext
    ) -> CollectorOutput:
        output = CollectorOutput()
        seen = set((ctx.previous_payload or {}).get("seen", []))
        identities: set[str] = set()
        root = Path(project.root).resolve()
        try:
            metadata = _repository(root, ctx)
            prefix = [
                "git",
                "--no-pager",
                "--literal-pathspecs",
                "--git-dir",
                str(metadata),
                "--work-tree",
                str(root),
                "-c",
                "core.quotepath=off",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.untrackedCache=false",
            ]

            def command(*args: str) -> str:
                result = run([*prefix, *args], timeout=ctx.remaining(), cwd=root)
                if result.returncode:
                    raise ProcessError("git_command_failed")
                if len(result.stdout) > ctx.limits.max_project_package_chars * 4:
                    raise ProcessError("git_output_too_large")
                return result.stdout

            def add(draft: EvidenceDraft) -> None:
                key = content_hash(
                    canonical([draft.kind, draft.locator, content_hash(draft.content)])
                )
                identities.add(key)
                if key not in seen:
                    output.evidence.append(draft)

            def allowed(name: str, *, deleted: bool = False) -> bool:
                path = Path(name)
                if path.is_absolute() or ".." in path.parts or _excluded(path, project.exclude):
                    return False
                if project.include and not any(
                    path.match(pattern)
                    or fnmatch.fnmatchcase(name, pattern)
                    or (pattern.startswith("**/") and path.match(pattern[3:]))
                    for pattern in project.include
                ):
                    return False
                if deleted:
                    if not (root / path).resolve().is_relative_to(root):
                        return False
                    return True
                try:
                    safe_path(
                        root, name, exclude=project.exclude, max_bytes=ctx.limits.max_file_bytes
                    )
                    return True
                except ReadError as error:
                    if str(error) != "excluded":
                        output.omitted.append(Omission(name, str(error)))
                    return False

            def diff(
                name: str,
                args: list[str],
                locator: str,
                event: datetime | None,
                blob: str | None = None,
            ) -> None:
                value = command(*args, "--no-ext-diff", "--no-textconv", "--no-renames", "--", name)
                binary = "Binary files " in value or "GIT binary patch" in value
                excerpt = (
                    "Archivo binario modificado; contenido omitido."
                    if binary
                    else value[: ctx.limits.max_diff_chars_per_file]
                )
                if len(value) > ctx.limits.max_diff_chars_per_file and not binary:
                    output.omitted.append(Omission(name, "diff_truncated"))
                add(
                    EvidenceDraft(
                        "diff",
                        locator,
                        value,
                        excerpt[: ctx.limits.max_excerpt_chars],
                        ctx.observed_at,
                        event,
                        {"path": name, "binary": binary, "git_blob": blob},
                    )
                )

            # An unborn repository has worktree evidence but no history yet.
            head = run(
                [*prefix, "rev-parse", "--verify", "HEAD"], timeout=ctx.remaining(), cwd=root
            )
            if head.returncode == 0:
                args = [
                    "log",
                    "--max-count=5001",
                    "--format=%H%x00%cI%x00%an%x00%s",
                    "--no-show-signature",
                ]
                if since:
                    args.append("--since=" + utc(since))
                args.append("--until=" + utc(ctx.observed_at))
                lines = command(*args).splitlines()
                if len(lines) > 5000:
                    output.omitted.append(Omission("git:history", "commit_limit"))
                for line in lines[:5000]:
                    ctx.remaining()
                    parts = line.split("\0", 3)
                    if len(parts) != 4:
                        raise ValueError("invalid_git_history")
                    sha, date, author, subject = parts
                    event = event_time(date)
                    if event is None:
                        raise ValueError("invalid_commit_date")
                    files = command(
                        "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z", sha
                    ).split("\0")
                    names = [name for name in files if name and allowed(name, deleted=True)]
                    add(
                        EvidenceDraft(
                            "commit",
                            sha,
                            line,
                            subject[: ctx.limits.max_excerpt_chars],
                            ctx.observed_at,
                            event,
                            {"sha": sha, "author": author, "files": names},
                        )
                    )
                    for name in names:
                        tree = command("ls-tree", "-l", "-z", sha, "--", name)
                        size = tree.split("\t", 1)[0].split()[-1] if tree else "0"
                        if not size.isdigit():
                            output.omitted.append(Omission(name, "unsupported_git_entry"))
                            continue
                        if int(size) > ctx.limits.max_file_bytes:
                            output.omitted.append(Omission(name, "too_large"))
                            continue
                        diff(
                            name,
                            ["show", "--format=", sha],
                            sha + ":" + name,
                            event,
                            tree.split("\t", 1)[0].split()[2] if tree else None,
                        )
            # Status is porcelain v1 -z: paths are literal, including whitespace/newlines.
            entries = command(
                "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"
            ).split("\0")
            for entry in entries:
                if not entry:
                    continue
                status, name = entry[:2], entry[3:]
                if not allowed(name, deleted="D" in status):
                    continue
                if status == "??":
                    raw = read_bounded(
                        root, name, exclude=project.exclude, max_bytes=ctx.limits.max_file_bytes
                    )
                    binary = b"\0" in raw
                    excerpt = (
                        "Archivo binario nuevo; contenido omitido."
                        if binary
                        else raw.decode("utf-8", errors="replace")[: ctx.limits.max_excerpt_chars]
                    )
                    add(
                        EvidenceDraft(
                            "uncommitted",
                            "untracked:" + name,
                            raw,
                            excerpt,
                            ctx.observed_at,
                            meta={"path": name, "status": status, "binary": binary},
                        )
                    )
                else:
                    if status[0] != " ":
                        diff(name, ["diff", "--cached"], "staged:" + name, None)
                    if status[1] != " ":
                        diff(name, ["diff"], "worktree:" + name, None)
                    add(
                        EvidenceDraft(
                            "uncommitted",
                            "status:" + name,
                            status,
                            status + " " + name,
                            ctx.observed_at,
                            meta={"path": name, "status": status},
                        )
                    )
            branches = command(
                "for-each-ref", "--format=%(refname):%(objectname)", "refs/heads"
            ).splitlines()
            previous = set((ctx.previous_payload or {}).get("branches", []))
            for branch in branches:
                if branch not in previous:
                    add(
                        EvidenceDraft(
                            "branch", branch.split(":")[0], branch, branch, ctx.observed_at
                        )
                    )
            output.snapshot_payload = {"seen": sorted(identities), "branches": branches}
            if output.omitted:
                output.status = "partial"
            return output
        except (OSError, ValueError, ProcessError, TimeoutError) as error:
            reason = str(error) if isinstance(error, ReadError) else "git_unavailable"
            return CollectorOutput(status="failed", omitted=[Omission("git", reason)])
