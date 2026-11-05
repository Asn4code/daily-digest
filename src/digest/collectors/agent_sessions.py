"""Read explicitly configured Codex JSONL sessions, excluding tools and secrets."""

import json
import re
from datetime import datetime
from pathlib import Path

from digest.collectors.base import (
    CaptureContext,
    CollectorOutput,
    EvidenceDraft,
    Omission,
    canonical,
    content_hash,
)
from digest.collectors.files import discover
from digest.collectors.kanvas import event_time
from digest.config import ProjectConfig
from digest.util.fs import ReadError, read_bounded


def redact(text: str, secret_values: tuple[str, ...] = ()) -> str:
    for value in sorted(secret_values, key=len, reverse=True):
        if value:
            text = text.replace(value, "[redactado]")
    text = re.sub(
        r'(?i)([\w.-]*(?:api[_-]?key|password|secret|token)[\w.-]*["\x27]?\s*[=:]\s*)'
        r'(?:"[^"\n]*"|\x27[^\x27\n]*\x27|[^\s,;]+)',
        r"\1[redactado]",
        text,
    )
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9_.~+/-]+=*", "Bearer [redactado]", text)
    return re.sub(r"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}", "[redactado]", text)


class AgentSessionsCollector:
    source = "agent_sessions"
    phase = 2

    def collect(
        self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext
    ) -> CollectorOutput:
        evidence = []
        omitted = []
        seen = set((ctx.previous_payload or {}).get("seen", []))
        identities = set()
        remaining = ctx.limits.max_project_package_chars
        for configured in project.agent_sessions:
            root = Path(configured)
            if not root.is_absolute():
                root = Path(project.root) / root
                if not root.resolve().is_relative_to(Path(project.root).resolve()):
                    omitted.append(Omission(configured, "outside_root"))
                    continue
            root = root.resolve()
            if not root.is_dir():
                omitted.append(Omission(configured, "session_directory_missing"))
                continue
            count = 0
            paths, scan_errors = discover(
                project.model_copy(update={"root": str(root)}), ctx, ["**/*.jsonl"]
            )
            omitted.extend(scan_errors)
            for relative in paths:
                name = root / relative
                count += 1
                if count > 1000:
                    omitted.append(Omission(configured, "session_scan_limit"))
                    break
                try:
                    ctx.remaining()
                    raw = read_bounded(
                        root, name.relative_to(root), max_bytes=ctx.limits.max_file_bytes
                    )
                    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
                    if not rows or rows[0].get("type") != "session_meta":
                        omitted.append(Omission(name.name, "unknown_session_format"))
                        continue
                    meta = rows[0].get("payload", {})
                    cwd = meta.get("cwd")
                    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
                        continue
                    current_directory = Path(cwd).resolve()
                    session_id = str(meta.get("id", content_hash(raw)[:16]))
                    for index, row in enumerate(rows[1:], 1):
                        ctx.remaining()
                        payload = row.get("payload", {})
                        if row.get("type") == "turn_context" and isinstance(
                            payload.get("cwd"), str
                        ):
                            current_directory = Path(payload["cwd"]).resolve()
                        if not current_directory.is_relative_to(Path(project.root).resolve()):
                            continue
                        if row.get("type") != "response_item" or payload.get("type") != "message":
                            continue
                        if payload.get("role") not in {"user", "assistant"}:
                            continue
                        text = "\n".join(
                            str(c.get("text", ""))
                            for c in payload.get("content", [])
                            if c.get("type") in {"input_text", "output_text"}
                        )
                        text = redact(text, ctx.secrets)
                        if not text:
                            continue
                        if len(text) > remaining:
                            omitted.append(Omission(name.name, "session_text_budget"))
                            break
                        remaining -= len(text)
                        identity = content_hash(canonical([session_id, index, text]))
                        identities.add(identity)
                        if identity in seen:
                            continue
                        evidence.append(
                            EvidenceDraft(
                                "agent_session",
                                session_id + "#message/" + str(index),
                                text,
                                text[: ctx.limits.max_excerpt_chars],
                                ctx.observed_at,
                                event_time(row.get("timestamp")),
                                {
                                    "agent": "codex",
                                    "role": payload["role"],
                                    "session_id": session_id,
                                },
                            )
                        )
                except (OSError, ValueError, TypeError, KeyError, TimeoutError) as error:
                    omitted.append(
                        Omission(
                            name.name,
                            str(error) if isinstance(error, ReadError) else "session_unreadable",
                        )
                    )
        return CollectorOutput(
            evidence, "partial" if omitted else "ok", omitted, {"seen": sorted(identities)}
        )
