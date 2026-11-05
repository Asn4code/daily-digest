"""PDF generation restricted to trusted HTML and local raster assets."""

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from weasyprint import HTML
from weasyprint.urls import FatalURLFetchingError, URLFetcher

from digest.publish.files import create


class RasterFetcher(URLFetcher):  # type: ignore[misc]
    """Adapter for WeasyPrint's untyped URLFetcher interface."""

    def __init__(self, directory: Path) -> None:
        super().__init__(allowed_protocols={"file"}, allow_redirects=False, fail_on_errors=True)
        self.root = directory.resolve()

    def fetch(self, url: str, headers: dict[str, str] | None = None) -> Any:
        parsed = urlsplit(url)
        path = Path(unquote(parsed.path)).resolve()
        if (
            parsed.scheme != "file"
            or parsed.netloc
            or not path.is_relative_to(self.root)
            or path.suffix != ".png"
        ):
            raise FatalURLFetchingError("PDF resource outside permitted raster directory")
        return super().fetch(url, headers)


def generate(directory: Path) -> Path:
    output = directory / "report.pdf"
    if output.is_symlink():
        raise ValueError("Invalid PDF output path")
    if output.is_file():
        return output
    value = HTML(
        string=(directory / "report.html").read_text(),
        base_url=str(directory),
        url_fetcher=RasterFetcher(directory),
    ).write_pdf()
    if not isinstance(value, bytes) or not value.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF output")
    create(output, value)
    return output
