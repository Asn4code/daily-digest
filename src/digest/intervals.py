"""UTC intervals with Europe/Madrid calendar boundaries and explicit publication."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from digest.collectors.base import utc


@dataclass(frozen=True)
class Interval:
    id: int
    kind: str
    start: datetime
    end: datetime


def open_interval(
    db: sqlite3.Connection,
    now: datetime,
    *,
    kind: Literal["daily", "weekly", "preview"] = "daily",
    requested_by: Literal["timer", "web", "cli"] = "cli",
    timezone: str = "Europe/Madrid",
    since: datetime | None = None,
    until: datetime | None = None,
) -> Interval | None:
    zone = ZoneInfo(timezone)
    utc(now)
    end = until or now
    local = now.astimezone(zone)
    if kind == "weekly":
        date = local.date()
        if requested_by == "timer":
            date -= timedelta(days=(date.weekday() - 5) % 7)
        end = until or datetime.combine(date, time(), zone)
        start = since or datetime.combine(date - timedelta(days=7), time(), zone)
    else:
        row = db.execute(
            "SELECT end_at FROM interval WHERE kind='daily' AND closed=1 "
            "ORDER BY end_at DESC LIMIT 1"
        ).fetchone()
        start = since or (
            datetime.fromisoformat(row[0]) if row else datetime.combine(local.date(), time(), zone)
        )
        if kind == "daily" and requested_by == "timer" and row and since is None and until is None:
            latest = datetime.fromisoformat(row[0])
            same_day = latest.astimezone(zone).date() == local.date()
            fresh = db.execute(
                "SELECT 1 FROM evidence WHERE observed_at>? AND observed_at<=? LIMIT 1",
                (utc(latest), utc(end)),
            ).fetchone()
            if same_day and not fresh:
                return None
    if start >= end:
        raise ValueError("Interval start must precede end")
    cursor = db.execute(
        "INSERT INTO interval(kind,start_at,end_at,requested_by) VALUES (?,?,?,?)",
        (kind, utc(start), utc(end), requested_by),
    )
    assert cursor.lastrowid is not None
    return Interval(cursor.lastrowid, kind, start.astimezone(UTC), end.astimezone(UTC))


def close_interval(db: sqlite3.Connection, interval_id: int, report_id: str) -> None:
    row = db.execute(
        "SELECT i.kind,i.end_at,r.status FROM interval i JOIN report r ON r.interval_id=i.id "
        "WHERE i.id=? AND r.id=?",
        (interval_id, report_id),
    ).fetchone()
    if not row or row[2] != "ready":
        raise ValueError("Report must be published before closing")
    if row[0] == "preview":
        return
    db.execute("UPDATE interval SET closed=1 WHERE id=?", (interval_id,))
    if row[0] == "daily":
        db.execute(
            "INSERT INTO meta(key,value) VALUES ('last_closed_daily',?) ON CONFLICT(key) "
            "DO UPDATE SET value=max(value,excluded.value)",
            (row[1],),
        )


def pending_days(
    db: sqlite3.Connection, now: datetime, *, timezone: str = "Europe/Madrid"
) -> list[tuple[datetime, datetime]]:
    zone = ZoneInfo(timezone)
    utc(now)
    today = now.astimezone(zone).date()
    result = []
    for offset in range(7, 0, -1):
        date = today - timedelta(days=offset)
        start = datetime.combine(date, time(), zone).astimezone(UTC)
        end = datetime.combine(date + timedelta(days=1), time(), zone).astimezone(UTC)
        row = db.execute(
            "SELECT 1 FROM evidence e WHERE COALESCE(e.event_at,e.observed_at)>=? "
            "AND COALESCE(e.event_at,e.observed_at)<? AND NOT EXISTS "
            "(SELECT 1 FROM interval i WHERE i.kind='daily' AND i.closed=1 "
            "AND i.start_at<=COALESCE(e.event_at,e.observed_at) "
            "AND i.end_at>COALESCE(e.event_at,e.observed_at)) LIMIT 1",
            (utc(start), utc(end)),
        ).fetchone()
        if row:
            result.append((start, end))
    return result
