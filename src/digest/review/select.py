"""Offer an open review first, without hiding any other result."""

import sqlite3

from digest.report.model import Report


def select(db: sqlite3.Connection, report: Report) -> dict[str, str] | None:
    row = db.execute(
        "SELECT id,result_id FROM review WHERE decision IS NULL ORDER BY submitted_at,id LIMIT 1"
    ).fetchone()
    if row:
        return {
            "review_id": str(row[0]),
            "result_id": str(row[1]),
            "why": "Retoma tu revisión abierta.",
        }
    candidate = report.sections.get("conceptual", {}).get("review_candidate")
    ordered = ([candidate["result_id"]] if candidate else []) + [r.id for r in report.results]
    for result_id in dict.fromkeys(ordered):
        row = db.execute("SELECT review_state FROM result WHERE id=?", (result_id,)).fetchone()
        if row and row[0] != "closed_by_human":
            return {
                "result_id": result_id,
                "review_id": "",
                "why": "Elige este resultado o cualquier otro del informe.",
            }
    return None
