"""Document diffs and raster-only figures from read-only project files."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from digest.collectors.base import CaptureContext
from digest.collectors.docs import DocsCollector
from digest.collectors.figures import FiguresCollector
from digest.config import ProjectConfig
from digest.util.fs import ReadError
from tests.fixtures.make_projects import PNG


def project(tmp_path: Path) -> tuple[ProjectConfig, CaptureContext]:
    root = tmp_path / "project"
    root.mkdir()
    return ProjectConfig(
        id="test", name="Test", root=str(root), include=["**/*"], figures=["figures/*"]
    ), CaptureContext(tmp_path / "service", datetime.now(UTC))


def test_documents_include_reports_and_diff(tmp_path: Path) -> None:
    p, c = project(tmp_path)
    root = Path(p.root)
    (root / "report.md").write_text("Initial result\n")
    first = DocsCollector().collect(p, None, c)
    assert first.status == "ok" and len(first.evidence) == 1
    c.previous_payload = first.snapshot_payload
    assert not DocsCollector().collect(p, None, c).evidence
    (root / "report.md").write_text("Updated result\n")
    changed = DocsCollector().collect(p, None, c)
    assert "-Initial result" in changed.evidence[0].meta["diff"]
    assert "+Updated result" in changed.evidence[0].meta["diff"]


def test_T07_changed_document_is_omitted(tmp_path: Path) -> None:
    p, c = project(tmp_path)
    (Path(p.root) / "report.md").write_text("data")
    with patch("digest.collectors.docs.read_bounded", side_effect=ReadError("changed_during_read")):
        output = DocsCollector().collect(p, None, c)
    assert output.status == "partial" and not output.evidence
    assert output.omitted[0].reason == "changed_during_read"


def test_T10_exclusions_apply_before_read(tmp_path: Path) -> None:
    p, c = project(tmp_path)
    with (Path(p.root) / "trajectory.xtc").open("wb") as stream:
        stream.truncate(3_000_000_000)
    (Path(p.root) / ".env").write_text("private")
    with patch("digest.collectors.docs.read_bounded", side_effect=AssertionError("must not read")):
        output = DocsCollector().collect(p, None, c)
    assert output.status == "ok" and not output.evidence


def test_figures_store_only_png_and_deduplicate(tmp_path: Path) -> None:
    p, c = project(tmp_path)
    folder = Path(p.root) / "figures"
    folder.mkdir()
    (folder / "image.png").write_bytes(PNG)
    (folder / "plot.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
        '<rect width="40" height="20" fill="blue"/></svg>'
    )
    image = Image.new("RGB", (40, 20), "blue")
    image.save(folder / "page.pdf")
    image.close()
    output = FiguresCollector().collect(p, None, c)
    assert output.status == "ok", output.omitted
    assert len(output.evidence) == 3
    for evidence in output.evidence:
        thumb = Path(evidence.meta["thumbnail"])
        assert thumb.suffix == ".png"
        with Image.open(thumb) as rendered:
            assert max(rendered.size) <= 1200
        assert evidence.meta["provenance"]["kind"] == "unverified"
    assert not list(c.data_dir.rglob("*.svg"))
    assert not list(c.data_dir.rglob("*.pdf"))
    c.previous_payload = output.snapshot_payload
    assert not FiguresCollector().collect(p, None, c).evidence


def test_external_svg_resource_is_never_fetched(tmp_path: Path) -> None:
    p, c = project(tmp_path)
    folder = Path(p.root) / "figures"
    folder.mkdir()
    (folder / "remote.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" width="40" height="20">'
        '<image xlink:href="https://example.invalid/secret.png" width="40" height="20"/></svg>'
    )
    with patch("urllib.request.urlopen", side_effect=AssertionError("no external fetch")):
        output = FiguresCollector().collect(p, None, c)
    assert output.status == "partial" and not output.evidence


def test_figure_provenance_requires_matching_git_blob(tmp_path: Path) -> None:
    import hashlib

    from digest.collectors.base import EvidenceDraft

    p, c = project(tmp_path)
    folder = Path(p.root) / "figures"
    folder.mkdir()
    (folder / "image.png").write_bytes(PNG)
    blob = hashlib.sha1(
        b"blob " + str(len(PNG)).encode() + b"\0" + PNG, usedforsecurity=False
    ).hexdigest()
    c.related_evidence = [
        EvidenceDraft(
            "diff",
            "a" * 40 + ":figures/image.png",
            "",
            "",
            c.observed_at,
            c.observed_at,
            {"path": "figures/image.png", "git_blob": blob},
        )
    ]
    output = FiguresCollector().collect(p, None, c)
    assert output.evidence[0].meta["provenance"] == {"kind": "git", "commit": "a" * 40}
    c.related_evidence[0].meta["git_blob"] = "b" * 40
    output = FiguresCollector().collect(p, None, c)
    assert output.evidence[0].meta["provenance"]["kind"] == "unverified"


def test_generated_html_report_is_read_as_text(tmp_path: Path) -> None:
    p, c = project(tmp_path)
    (Path(p.root) / "report.html").write_text(
        "<h1>Resultado</h1><p>Control &lt;correcto&gt;</p>"
        '<script>fetch("https://example.invalid/private")</script>'
    )
    output = DocsCollector().collect(p, None, c)
    assert output.status == "ok"
    assert "Control <correcto>" in output.evidence[0].excerpt
    assert "fetch" not in output.evidence[0].excerpt
