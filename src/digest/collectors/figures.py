"""Raster-only thumbnails from bounded figure inputs, with external fetch disabled."""

import hashlib
import io
import warnings
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium
from cairosvg.surface import PNGSurface
from PIL import Image

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


def deny_resource(url: str, resource_type: str) -> bytes:
    raise ValueError("external_svg_resource")


def thumbnail(raw: bytes, suffix: str) -> bytes:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        image: Image.Image
        if suffix == ".svg":
            converted = PNGSurface.convert(
                bytestring=raw,
                unsafe=False,
                output_width=1200,
                output_height=1200,
                url_fetcher=deny_resource,
            )
            if not isinstance(converted, bytes):
                raise ValueError("invalid_svg")
            image = Image.open(io.BytesIO(converted))
        elif suffix == ".pdf":
            with pdfium.PdfDocument(raw) as document:
                page = document[0]
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    raise ValueError("invalid_pdf_size")
                bitmap = page.render(scale=min(1200 / width, 1200 / height))
                image = bitmap.to_pil().copy()
                bitmap.close()
                page.close()
        else:
            image = Image.open(io.BytesIO(raw))
        try:
            if image.width * image.height > 16_000_000:
                raise ValueError("figure_pixel_limit")
            image.load()
            image.thumbnail((1200, 1200))
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA")
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
        finally:
            image.close()


def provenance(raw: bytes, name: str, ctx: CaptureContext) -> dict[str, str]:
    blob = b"blob " + str(len(raw)).encode() + b"\0" + raw
    for evidence in sorted(
        ctx.related_evidence,
        key=lambda item: item.event_at.isoformat() if item.event_at else "",
        reverse=True,
    ):
        expected = evidence.meta.get("git_blob")
        if evidence.meta.get("path") != name or not isinstance(expected, str):
            continue
        actual = (
            hashlib.sha1(blob, usedforsecurity=False).hexdigest()
            if len(expected) == 40
            else hashlib.sha256(blob).hexdigest()
        )
        if actual == expected and evidence.event_at is not None:
            return {"kind": "git", "commit": evidence.locator.split(":", 1)[0]}
    return {"kind": "unverified", "reason": "no_explicit_commit_or_log_link"}


class FiguresCollector:
    source = "figures"
    phase = 1

    def collect(
        self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext
    ) -> CollectorOutput:
        if ctx.data_dir.resolve().is_relative_to(Path(project.root).resolve()):
            return CollectorOutput(
                status="failed", omitted=[Omission("figures", "output_inside_project")]
            )
        files, omitted = discover(project, ctx, project.figures)
        previous = (ctx.previous_payload or {}).get("files", {})
        payload = {}
        evidence = []
        for name in files:
            suffix = Path(name).suffix.lower()
            if suffix not in {".png", ".svg", ".pdf"}:
                continue
            try:
                ctx.remaining()
                raw = read_bounded(
                    Path(project.root),
                    name,
                    exclude=project.exclude,
                    max_bytes=ctx.limits.max_file_bytes,
                )
                hashed = content_hash(raw)
                if previous.get(name) == hashed:
                    payload[name] = hashed
                    continue
                rendered = thumbnail(raw, suffix)
                ctx.remaining()
                directory = ctx.data_dir / "figures" / project.id
                directory.mkdir(parents=True, exist_ok=True)
                target = directory / (hashed + ".png")
                if not target.exists():
                    with target.open("xb") as stream:
                        stream.write(rendered)
                payload[name] = hashed
                evidence.append(
                    EvidenceDraft(
                        "figure",
                        name,
                        raw,
                        f"Figura: {name}",
                        ctx.observed_at,
                        meta={
                            "path": name,
                            "thumbnail": str(target),
                            "format": "png",
                            "provenance": provenance(raw, name, ctx),
                        },
                    )
                )
            except (
                OSError,
                ValueError,
                RuntimeError,
                TimeoutError,
                Image.DecompressionBombWarning,
                Image.DecompressionBombError,
            ) as error:
                reason = str(error) if isinstance(error, ReadError) else "figure_unreadable"
                if reason != "excluded":
                    omitted.append(Omission(name, reason))
        return CollectorOutput(
            evidence, "partial" if omitted else "ok", omitted, {"files": payload}
        )
