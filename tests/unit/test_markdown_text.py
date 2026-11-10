"""Untrusted Markdown text stays literal, including quotes and HTML entities."""

from html.parser import HTMLParser

import pytest
from markdown_it import MarkdownIt

from digest.report.render_md import escape


class Parsed(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    def handle_data(self, data):
        self.text.append(data)


@pytest.mark.parametrize(
    "source",
    [
        'L\'apóstrofo y las comillas: "resultado".',
        "&amp; &#x27; &#39; &lt;script&gt; \\ & desconocido",
        '<script>alert("x")</script><img src=x onerror=alert(1)>',
        "[abrir](javascript:alert(2)) ![imagen](https://example.test/a.png)",
        "<https://example.test/> <user@example.test>",
        "**resaltar** `código` # título | celda | $fórmula$ ==marca== [[nota]]",
    ],
)
def test_untrusted_text_round_trips_without_executable_markup(source):
    rendered = MarkdownIt("commonmark", {"html": True}).render(escape(source))
    parsed = Parsed()
    parsed.feed(rendered)
    assert "".join(parsed.text).rstrip("\n") == source
    assert parsed.tags == ["p"]


def test_multiline_source_cannot_create_blocks():
    source = "# cabecera\n> cita\n- lista\n```python\nalert(1)\n```"
    rendered = MarkdownIt("commonmark", {"html": True}).render(escape(source))
    parsed = Parsed()
    parsed.feed(rendered)
    assert parsed.tags == ["p"]
    assert "".join(parsed.text).rstrip("\n") == source
