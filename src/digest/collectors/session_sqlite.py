"""Bounded immutable SQLite readers for verified OpenCode and Hermes layouts."""

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from digest.collectors.base import (
    CaptureContext,
    CollectorOutput,
    EvidenceDraft,
    Omission,
    canonical,
    content_hash,
)
from digest.config import ProjectConfig
from digest.util.fs import _fingerprint, safe_path
from digest.util.redact import redact

MAX_DATABASE_BYTES = 2_000_000_000
MAX_ROWS = 200


def collect(
    path: Path, project: ProjectConfig, ctx: CaptureContext, seen: set[str]
) -> CollectorOutput:
    omitted = []
    evidence = []
    identities = set()
    try:
        target = safe_path(
            path.parent, path.name, exclude=project.exclude, max_bytes=MAX_DATABASE_BYTES
        )
        before = _fingerprint(target.stat())
        if Path(str(target) + "-wal").exists() and Path(str(target) + "-wal").stat().st_size:
            omitted.append(Omission(path.name, "sqlite_wal_not_read"))
        with closing(
            sqlite3.connect(
                "file:" + quote(str(target), safe="/") + "?mode=ro&immutable=1", uri=True
            )
        ) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA temp_store=MEMORY")
            db.execute("PRAGMA cache_size=-2048")
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, ctx.limits.max_file_bytes)
            steps = 0

            def stop() -> int:
                nonlocal steps
                steps += 1000
                try:
                    ctx.remaining()
                except TimeoutError:
                    return 1
                return int(steps > 500_000)

            db.set_progress_handler(stop, 1000)
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            root = str(Path(project.root).resolve())
            prefix = root.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
            bound = ctx.limits.max_excerpt_chars + 1
            rows: Iterable[tuple[Any, ...]]
            if {"session", "message", "part"} <= tables:
                agent = "opencode"
                sessions = [
                    row[0]
                    for row in db.execute(
                        "SELECT id FROM session WHERE directory=? OR directory LIKE ? ESCAPE '\\' "
                        "ORDER BY time_updated DESC LIMIT 21",
                        (root, prefix),
                    )
                ]
                if len(sessions) > 20:
                    omitted.append(Omission(path.name, "session_selection_limit"))
                if not sessions:
                    rows = iter([])
                else:
                    rows = db.execute(
                        "SELECT p.id,p.session_id,p.time_created,"
                        "substr(m.data,1,?),substr(p.data,1,?),s.directory "
                        "FROM part p JOIN message m ON m.id=p.message_id "
                        "AND m.session_id=p.session_id JOIN session s ON s.id=p.session_id "
                        "WHERE p.session_id IN (" + ",".join("?" for _ in sessions[:20]) + ") "
                        "ORDER BY p.time_created DESC LIMIT ?",
                        (
                            ctx.limits.max_file_bytes,
                            ctx.limits.max_file_bytes,
                            *sessions[:20],
                            MAX_ROWS + 1,
                        ),
                    )
            elif {"sessions", "messages"} <= tables:
                agent = "hermes"
                rows = db.execute(
                    "SELECT m.id,m.session_id,m.timestamp,m.role,substr(m.content,1,?),s.cwd "
                    "FROM messages m JOIN sessions s ON s.id=m.session_id "
                    "WHERE (s.cwd=? OR s.cwd LIKE ? ESCAPE '\\') "
                    "AND m.role IN ('user','assistant') "
                    "ORDER BY m.timestamp DESC LIMIT ?",
                    (ctx.limits.max_file_bytes, root, prefix, MAX_ROWS + 1),
                )
            else:
                raise ValueError("unknown_session_database")
            budget = ctx.limits.max_project_package_chars
            for index, (ident, session, date, role, body, cwd) in enumerate(rows):
                if not Path(cwd).resolve().is_relative_to(Path(project.root).resolve()):
                    continue
                ctx.remaining()
                if index >= MAX_ROWS:
                    omitted.append(Omission(path.name, "session_row_limit"))
                    break
                if agent == "opencode":
                    message = json.loads(role)
                    part = json.loads(body)
                    role = message.get("role")
                    if role not in {"user", "assistant"} or part.get("type") != "text":
                        continue
                    body = part.get("text", "")
                    date = float(date) / 1000
                if not isinstance(body, str):
                    omitted.append(Omission(path.name, "session_content_unsupported"))
                    continue
                if len(body) >= bound:
                    omitted.append(Omission(path.name, "session_excerpt_truncated"))
                text = redact(body, ctx.secrets)[: ctx.limits.max_excerpt_chars]
                if len(text) > budget:
                    omitted.append(Omission(path.name, "session_text_budget"))
                    break
                budget -= len(text)
                if not text:
                    continue
                event = None
                try:
                    event = datetime.fromtimestamp(float(date), UTC)
                except (ValueError, TypeError, OverflowError, OSError):
                    pass
                locator = agent + ":" + str(session) + "#message/" + str(ident)
                hashed = content_hash(canonical([locator, text]))
                identities.add(hashed)
                if hashed in seen:
                    continue
                evidence.append(
                    EvidenceDraft(
                        "agent_session",
                        locator,
                        text,
                        text,
                        ctx.observed_at,
                        event,
                        {"agent": agent, "role": role, "session_id": str(session)},
                    )
                )
        if _fingerprint(target.stat()) != before:
            return CollectorOutput(
                status="partial", omitted=[Omission(path.name, "changed_during_read")]
            )
    except (OSError, ValueError, TypeError, sqlite3.Error, TimeoutError):
        return CollectorOutput(
            status="partial", omitted=[Omission(path.name, "session_database_unreadable")]
        )
    return CollectorOutput(
        evidence, "partial" if omitted else "ok", omitted, {"seen": sorted(identities)}
    )
