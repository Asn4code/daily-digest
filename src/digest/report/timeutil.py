"""Local calendar display for UTC report records."""

from datetime import datetime
from zoneinfo import ZoneInfo


def display(value: str, timezone: str = "Europe/Madrid") -> str:
    return (
        datetime.fromisoformat(value).astimezone(ZoneInfo(timezone)).strftime("%d/%m/%Y %H:%M %Z")
    )
