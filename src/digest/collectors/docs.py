"""Capture bounded documentary text and diffs as untrusted evidence data."""

import difflib
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import pypdfium2 as pdfium

from digest.collectors.base import (
    CaptureContext,
    CollectorOutput,
    EvidenceDraft,
    Omission,
    content_hash,
)
from digest.collectors.files import discover
from digest.config import ProjectConfig
from digest.util.fs import ReadError, read_bounded


class _PlainHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def document_text(raw: bytes, suffix: str, ctx: CaptureContext) -> str:
    if suffix == ".pdf":
        parts = []
        remaining = ctx.limits.max_project_package_chars
        with pdfium.PdfDocument(raw) as document:
            for index in range(min(len(document), 100)):
                ctx.remaining()
                page = document[index]
                textpage = page.get_textpage()
                try:
                    size = textpage.count_chars()
                    if size > remaining:
                        raise ValueError("document_text_limit")
                    parts.append(textpage.get_text_range(0, size))
                    remaining -= size
                finally:
                    textpage.close()
                    page.close()
            if len(document) > 100:
                raise ValueError("document_page_limit")
        return "\n".join(parts)
    text = raw.decode("utf-8")
    if suffix in {".html", ".htm"}:
        parser = _PlainHTML()
        parser.feed(text)
        return "\n".join(parser.parts)
    return text


class DocsCollector:
    source = "docs"
    phase = 1

    def collect(
        self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext
    ) -> CollectorOutput:
        files, omitted = discover(project, ctx, project.include or ["**/*"])
        previous = (ctx.previous_payload or {}).get("files", {})
        payload = {}
        evidence = []
        budget = ctx.limits.max_project_package_chars
        for name in files:
            if (
                Path(name).suffix.lower() not in {".md", ".rst", ".txt", ".html", ".htm", ".pdf"}
                and Path(name).name.lower() != "readme"
            ):
                continue
            try:
                ctx.remaining()
                raw = read_bounded(
                    Path(project.root),
                    name,
                    exclude=project.exclude,
                    max_bytes=ctx.limits.max_file_bytes,
                )
                text = document_text(raw, Path(name).suffix.lower(), ctx)
                if len(text) > budget:
                    omitted.append(Omission(name, "snapshot_budget"))
                    continue
                budget -= len(text)
                hashed = content_hash(raw)
                payload[name] = {"hash": hashed, "text": text}
                old = previous.get(name, {})
                if old.get("hash") == hashed:
                    continue
                difference = "".join(
                    difflib.unified_diff(
                        old.get("text", "").splitlines(True),
                        text.splitlines(True),
                        fromfile=name + " (anterior)",
                        tofile=name,
                    )
                )
                if len(difference) > ctx.limits.max_diff_chars_per_file:
                    omitted.append(Omission(name, "diff_truncated"))
                evidence.append(
                    EvidenceDraft(
                        "doc_change",
                        name,
                        raw,
                        text[: ctx.limits.max_excerpt_chars],
                        ctx.observed_at,
                        meta={
                            "path": name,
                            "diff": difference[: ctx.limits.max_diff_chars_per_file],
                        },
                    )
                )
            except (ValueError, RuntimeError, OSError, TimeoutError) as error:
                reason = str(error) if isinstance(error, ReadError) else "unreadable"
                if reason != "excluded":
                    omitted.append(Omission(name, reason))
        return CollectorOutput(
            evidence, "partial" if omitted else "ok", omitted, {"files": payload}
        )
