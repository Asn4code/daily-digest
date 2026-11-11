"""Separate human notes and generated contrasts; only explicit 'lista' is imported."""

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from digest.collectors.base import canonical
from digest.config import Config
from digest.publish.files import create, destination
from digest.report.model import Report
from digest.report.render_md import escape
from digest.review import records
from digest.review.select import select
from digest.util.fs import read_bounded


def note_path(config: Config, name: str) -> Path:
    if Path(name).name != name or not name.endswith(".md"):
        raise ValueError("Invalid review note name")
    vault = Path(config.paths.obsidian_vault)
    lexical = vault / config.paths.obsidian_reviews_dir / name
    if lexical.is_symlink():
        raise ValueError("Review notes cannot be symbolic links")
    return destination(config, vault, f"{config.paths.obsidian_reviews_dir}/{name}")


def template(db: sqlite3.Connection, config: Config, report: Report) -> None:
    chosen = select(db, report)
    if chosen is None or chosen["review_id"]:
        return
    result = records.item(report, chosen["result_id"])
    date = datetime.fromisoformat(report.end_at).astimezone(ZoneInfo(config.timezone)).date()
    name = f"{date}-{result.id}.md"
    path = note_path(config, name)
    if not path.exists():
        body = (
            f"---\nresult: {result.id}\nestado: pendiente\nmodo: breve\n---\n"
            "## Mi explicación\n- Qué muestra:\n- Por qué importa:\n- Qué no sé:\n"
        )
        create(path, body.encode())
    # Keep the original binding: a new report must not repoint a human note.
    db.execute(
        "INSERT OR IGNORE INTO meta(key,value) VALUES (?,?)",
        ("review_note:" + name, canonical({"result": result.id, "report": report.id})),
    )


def import_ready(db: sqlite3.Connection, config: Config) -> int:
    rows = db.execute(
        "SELECT key,value FROM meta WHERE key LIKE 'review_note:%' ORDER BY key DESC LIMIT 200"
    ).fetchall()
    count = 0
    vault = Path(config.paths.obsidian_vault)
    for key, encoded in rows:
        try:
            name = key.removeprefix("review_note:")
            target = note_path(config, name)
            raw = read_bounded(vault, target.relative_to(vault.resolve()), max_bytes=32_000)
            digest = hashlib.sha256(raw).hexdigest()
            consumed = db.execute(
                "SELECT value FROM meta WHERE key=?", ("review_import:" + name,)
            ).fetchone()
            if consumed and consumed[0] == digest:
                continue
            text = raw.decode("utf-8")
            if not text.startswith("---\n"):
                continue
            _, front, body = text.split("---", 2)
            meta = yaml.safe_load(front)
            binding = json.loads(encoded)
            if (
                not isinstance(meta, dict)
                or meta.get("estado") != "lista"
                or meta.get("result") != binding["result"]
            ):
                continue
            mode = {"completo": "full", "breve": "short", "mínimo": "minimal"}.get(
                str(meta.get("modo"))
            )
            if mode is None:
                continue
            values: dict[str, str] = {}
            field: str | None = None
            for line in body.splitlines():
                match = re.match(r"^- ([^:]+):\s*(.*)$", line)
                if match:
                    field = next(
                        (k for k, label in records.FIELDS[mode].items() if label == match[1]), None
                    )
                    if field is None or field in values:
                        raise ValueError("Invalid note fields")
                    values[field] = match[2]
                elif field and line.strip() and not line.startswith("##"):
                    values[field] += "\n" + line.strip()
            db.execute("BEGIN IMMEDIATE")
            try:
                records.submit(
                    db,
                    config,
                    binding["report"],
                    binding["result"],
                    mode,
                    values,
                    requested_by="cli",
                    postpone=mode == "minimal" and not values.get("doubt"),
                )
                db.execute(
                    "INSERT INTO meta(key,value) VALUES (?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("review_import:" + name, digest),
                )
                db.commit()
            except BaseException:
                db.rollback()
                raise
            count += 1
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError, sqlite3.Error):
            continue
    return count


def publish(
    db: sqlite3.Connection, config: Config, review_id: str, *, channel: str | None = None
) -> dict[str, str]:
    if channel is not None and channel not in {"obsidian", "drive"}:
        raise ValueError("Unknown review channel")
    record, report = records.read(db, config, review_id)
    if record["decision"] is None:
        raise ValueError("A human decision is required")
    result = records.item(report, record["result_id"])
    date = datetime.fromisoformat(report.end_at).astimezone(ZoneInfo(config.timezone)).date()
    number = int(review_id.rsplit("_", 1)[1])
    suffix = "" if number == 1 else f"-r{number}"
    name = f"{date}-{result.id}-contraste{suffix}.md"
    lines = [
        "# Revisión · " + escape(result.title),
        "Resultado: " + escape(result.id),
        "Decisión humana: "
        + {
            "closed": "Cerrada por la persona",
            "needs_clarification": "Requiere aclaración",
            "postponed": "Pospuesta",
        }[record["decision"]],
        "## Mi explicación",
    ]
    lines.extend(
        escape(label) + ": " + escape(record["human_text"][field])
        for field, label in records.FIELDS[record["mode"]].items()
    )
    if record["contrast"]:
        for field, label in {
            "supported": "Respaldado",
            "omissions": "Omisiones relevantes",
            "unsupported": "Sin respaldo",
            "unverifiable": "No verificable",
            "summary_errors": "Correcciones al resumen automático",
        }.items():
            lines.append("## " + label)
            for claim in record["contrast"][field]:
                lines.append(
                    escape(claim["text"])
                    + (
                        " · " + escape(claim["why"])
                        if "why" in claim
                        else " [" + ", ".join(claim["evidence"]) + "]"
                    )
                )
    lines.extend(["## Dudas", *(escape(d) for d in record["doubts"])])
    lines.extend(
        ["## Procedencia", *(escape(k) + ": " + escape(v) for k, v in record["model_info"].items())]
    )
    data = Path(config.paths.data_dir)
    directory = destination(config, data, "reviews/" + review_id)
    create(directory / "review.md", ("\n\n".join(lines) + "\n").encode())
    create(directory / "review.json", canonical(record).encode())
    outcomes = {}
    selected = {channel} if channel else {"obsidian", "drive"}
    for channel in ("obsidian", "drive"):
        if channel not in selected:
            continue
        row = db.execute(
            "SELECT id,state FROM delivery WHERE review_id=? AND channel=? ORDER BY id LIMIT 1",
            (review_id, channel),
        ).fetchone()
        if row is None:
            cursor = db.execute(
                "INSERT INTO delivery(report_id,review_id,channel,state,updated_at) "
                "VALUES (?,?,?,'pending',?)",
                (report.id, review_id, channel, record["decided_at"]),
            )
            row = (cursor.lastrowid, "pending")
        did, state = row
        if state == "sent":
            outcomes[channel] = "sent"
            continue
        db.execute("UPDATE delivery SET attempts=attempts+1 WHERE id=?", (did,))
        try:
            if channel == "obsidian":
                target = note_path(config, name)
                create(target, (directory / "review.md").read_bytes())
            else:
                from digest.util.proc import run

                remote = config.drive.remote.rstrip("/") + "/reviews/" + review_id
                args = ["rclone"] + (
                    ["--config", "/dev/null"] if remote.startswith(":local:") else []
                )
                response = run(
                    [
                        *args,
                        "copy",
                        "--immutable",
                        "--retries",
                        "1",
                        "--low-level-retries",
                        "1",
                        str(directory),
                        remote,
                    ],
                    timeout=300,
                )
                if response.returncode:
                    raise RuntimeError("Review copy failed")
            db.execute("UPDATE delivery SET state='sent',last_error=NULL WHERE id=?", (did,))
            outcomes[channel] = "sent"
        except (OSError, ValueError, RuntimeError):
            db.execute(
                "UPDATE delivery SET state='failed',last_error='review_delivery_failed' WHERE id=?",
                (did,),
            )
            outcomes[channel] = "failed"
    return outcomes
