"""Render a static report with Jinja autoescaping and local assets only."""

from importlib.resources import files

from jinja2 import Environment, select_autoescape

from digest.report.model import Report
from digest.report.observations import origin_label
from digest.report.timeutil import display
from digest.report.views import CONFIDENCE, PRIORITIES, daily_view, weekly_checks, weekly_notices

ENV = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
ENV.filters["localtime"] = display
ENV.filters["originlabel"] = origin_label
ENV.filters["confidence"] = lambda value: CONFIDENCE[value]
ENV.filters["priority"] = lambda value: PRIORITIES[value]
TEMPLATE = files("digest.report").joinpath("templates/report.html").read_text(encoding="utf-8")


def render(report: Report) -> str:
    return ENV.from_string(TEMPLATE).render(
        report=report,
        view=daily_view(report),
        critical=weekly_checks(report),
        critical_highlights=weekly_checks(report, highlighted=True),
        critical_notices=weekly_notices(report),
    )
