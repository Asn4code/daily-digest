"""Serialize deterministic source captures into the evidence registry."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from digest.collectors.base import (
    CaptureContext,
    Collector,
    CollectorOutput,
    EvidenceDraft,
    Omission,
)
from digest.collectors.docs import DocsCollector
from digest.collectors.figures import FiguresCollector
from digest.collectors.git import GitCollector
from digest.collectors.kanvas import KanvasCollector
from digest.collectors.metrics import MetricsCollector
from digest.collectors.runs import RunsCollector
from digest.collectors.store import persist, previous_payload
from digest.config import Config
from digest.results import group_results


def validate_data_directory(config: Config) -> Path:
    data = Path(config.paths.data_dir).resolve()
    for project in config.projects:
        if data.is_relative_to(Path(project.root).resolve()):
            raise ValueError("Data directory overlaps an observed project")
    return data


def capture(
    db: sqlite3.Connection,
    config: Config,
    *,
    now: datetime | None = None,
    project_id: str | None = None,
) -> None:
    data = validate_data_directory(config)
    projects = [p for p in config.projects if project_id is None or p.id == project_id]
    if project_id and not projects:
        raise ValueError("Unknown project")
    instant = now or datetime.now(UTC)
    collectors: list[Collector] = [
        KanvasCollector(),
        GitCollector(),
        DocsCollector(),
        FiguresCollector(),
        MetricsCollector(),
        RunsCollector(),
    ]
    for project in projects:
        ctx = CaptureContext(data, instant, config.limits, kanvas_command=(config.kanvas.cli,))
        related: list[EvidenceDraft] = []
        for collector in collectors:
            ctx.previous_payload = previous_payload(db, project.id, collector.source)
            ctx.related_evidence = related
            try:
                output = collector.collect(project, None, ctx)
            except Exception:
                # A source failure must not suppress other sources or expose raw data.
                output = CollectorOutput(
                    status="failed", omitted=[Omission(collector.source, "collector_failed")]
                )
            persist(db, project, collector.source, output, ctx)
            related.extend(output.evidence)
    group_results(db)
