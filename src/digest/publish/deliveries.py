"""Track and retry each channel independently without replaying uncertain email."""

import sqlite3
from datetime import UTC, datetime
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import SMTP
from pathlib import Path

from digest.collectors.base import utc
from digest.config import Config
from digest.publish import drive, email, obsidian
from digest.publish.files import destination
from digest.report.loading import load_ready
from digest.report.pdf import generate

CHANNELS = ("obsidian", "drive", "email")


def deliver_report(
    db: sqlite3.Connection,
    config: Config,
    report_id: str,
    *,
    channel: str | None = None,
    force_uncertain: bool = False,
) -> dict[str, str]:
    report, path, _ = load_ready(db, config, report_id)
    if report.kind == "preview":
        raise ValueError("Report is not deliverable")
    data = Path(config.paths.data_dir).resolve()
    if channel is not None and channel not in CHANNELS:
        raise ValueError("Unknown channel")
    selected = [channel] if channel else list(CHANNELS)
    for name in selected:
        db.execute(
            "INSERT INTO delivery(report_id,channel,state,updated_at) "
            "SELECT ?,?,'pending',? WHERE NOT EXISTS "
            "(SELECT 1 FROM delivery WHERE report_id=? AND review_id IS NULL AND channel=?)",
            (report_id, name, utc(datetime.now(UTC)), report_id, name),
        )
    results = {}
    for name in CHANNELS:
        if name not in selected:
            continue
        delivery = db.execute(
            "SELECT id,state,remote_ref FROM delivery WHERE report_id=? AND review_id IS NULL "
            "AND channel=? ORDER BY id LIMIT 1",
            (report_id, name),
        ).fetchone()
        did, state, _ = delivery
        if state == "sent" or (state == "uncertain" and not force_uncertain):
            results[name] = state
            continue
        db.execute("UPDATE delivery SET attempts=attempts+1 WHERE id=?", (did,))

        def update(new_state: str, error: str | None = None, delivery_id: int = did) -> None:
            db.execute(
                "UPDATE delivery SET state=?,last_error=?,updated_at=? WHERE id=?",
                (new_state, error, utc(datetime.now(UTC)), delivery_id),
            )

        try:
            if name == "obsidian":
                remote = obsidian.publish(config, report, path.parent)
                from digest.review.notes import template as review_template

                review_template(db, config, report)
                db.execute("UPDATE delivery SET remote_ref=? WHERE id=?", (remote, did))
                update("sent")
            elif name == "drive":
                pdf = generate(path.parent)
                db.execute("UPDATE report SET pdf_path=? WHERE id=?", (str(pdf), report_id))
                remote = drive.publish(config, report, path.parent)
                db.execute("UPDATE delivery SET remote_ref=? WHERE id=?", (remote, did))
                update("sent")
            else:
                prior = db.execute(
                    "SELECT remote_ref FROM delivery WHERE report_id=? AND channel='drive' "
                    "AND state='sent' ORDER BY id LIMIT 1",
                    (report_id,),
                ).fetchone()
                link = None
                if prior:
                    try:
                        link = drive.url(config, prior[0])
                    except (OSError, RuntimeError):
                        pass
                outbox = destination(config, data, "outbox/" + report.id + ".eml")
                if outbox.exists():
                    message = BytesParser(policy=SMTP).parsebytes(outbox.read_bytes())
                    if not isinstance(message, EmailMessage):
                        raise ValueError("Invalid outbox message")
                else:
                    message = email.compose(config, report, path.parent, link)
                if str(message["Message-ID"]) != f"<{report.id}@daily-digest.local>":
                    raise ValueError("Outbox identity changed")
                if (
                    str(message["To"]) != config.email.to
                    or str(message["From"]) != config.email.from_address
                ):
                    raise ValueError("Outbox recipient changed")
                db.execute(
                    "UPDATE delivery SET message_id=? WHERE id=?", (str(message["Message-ID"]), did)
                )
                results[name] = email.send(config, message, outbox, update)
                continue
            results[name] = "sent"
        except Exception:
            update("failed", name + "_delivery_failed")
            results[name] = "failed"
    return results


def retry(
    db: sqlite3.Connection,
    config: Config,
    *,
    channel: str | None = None,
    force_uncertain: bool = False,
) -> dict[str, dict[str, str]]:
    rows = db.execute(
        "SELECT DISTINCT report_id FROM delivery WHERE report_id IS NOT NULL "
        "AND state IN ('pending','failed','uncertain')"
    ).fetchall()
    return {
        report_id: deliver_report(
            db, config, report_id, channel=channel, force_uncertain=force_uncertain
        )
        for (report_id,) in rows
    }
