"""Render a static report with Jinja autoescaping and local assets only."""

from importlib.resources import files

from jinja2 import Environment, select_autoescape

from digest.report.model import Report
from digest.report.timeutil import display

ENV = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
ENV.filters["localtime"] = display
TEMPLATE = files("digest.report").joinpath("templates/report.html").read_text(encoding="utf-8")


def render(report: Report) -> str:
    return ENV.from_string(TEMPLATE).render(report=report)
