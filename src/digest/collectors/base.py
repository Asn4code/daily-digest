"""Shared evidence and capture contracts."""

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from digest.config import LimitsConfig, ProjectConfig


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_hash(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("An aware timestamp is required")
    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class Omission:
    locator: str
    reason: str


@dataclass
class EvidenceDraft:
    kind: str
    locator: str
    content: bytes | str
    excerpt: str
    observed_at: datetime
    event_at: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None


@dataclass
class CollectorOutput:
    evidence: list[EvidenceDraft] = field(default_factory=list)
    status: Literal["ok", "partial", "failed"] = "ok"
    omitted: list[Omission] = field(default_factory=list)
    snapshot_payload: dict[str, Any] | None = None


@dataclass
class CaptureContext:
    data_dir: Path
    observed_at: datetime
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    previous_payload: dict[str, Any] | None = None
    kanvas_command: tuple[str, ...] = ("kanvas",)
    deadline: float | None = None
    related_evidence: list[EvidenceDraft] = field(default_factory=list)
    secrets: tuple[str, ...] = field(default=(), repr=False)

    def remaining(self) -> float:
        if self.deadline is None:
            self.deadline = time.monotonic() + self.limits.capture_timeout_seconds
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("capture_timeout")
        return remaining


class Collector(Protocol):
    source: str
    phase: int

    def collect(
        self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext
    ) -> CollectorOutput: ...
