"""One representation for reports and delivery channels."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Claim:
    text: str
    evidence: list[str]


@dataclass
class Figure:
    evidence: str
    path: str
    caption: str


@dataclass
class ResultEntry:
    id: str
    project: str
    title: str
    task_id: str | None
    review_state: str
    evidence: list[str]
    figures: list[Figure] = field(default_factory=list)

    @property
    def review_label(self) -> str:
        return {
            "pending": "Pendiente",
            "submitted": "Explicación enviada",
            "contrasted": "Contraste disponible",
            "needs_clarification": "Requiere aclaración",
            "closed_by_human": "Cerrada por la persona",
            "postponed": "Pospuesta",
        }[self.review_state]


@dataclass
class EvidenceEntry:
    id: str
    project: str
    kind: str
    locator: str
    excerpt: str
    observed_at: str
    event_at: str | None
    time_quality: str
    meta: dict[str, Any]
    content_hash: str | None = None


@dataclass
class Coverage:
    snapshot_id: int
    project: str
    source: str
    status: str
    omitted: list[dict[str, str]]


@dataclass
class Report:
    id: str
    kind: str
    start_at: str
    end_at: str
    created_at: str
    results: list[ResultEntry] = field(default_factory=list)
    open_threads: list[Claim] = field(default_factory=list)
    evidence: list[EvidenceEntry] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)
    mechanical: bool = True
    timezone: str = "Europe/Madrid"

    sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    packages: dict[str, dict[str, Any]] = field(default_factory=dict)
    model_info: dict[str, dict[str, str]] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    pending: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    observations: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_units: dict[str, list[str]] = field(default_factory=dict)

    @property
    def kind_label(self) -> str:
        return {"daily": "diario", "weekly": "semanal", "preview": "de avance"}[self.kind]
