"""Export one immutable human plan decision to approved vault and Drive paths."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from digest.collectors.base import canonical, utc
from digest.config import Config
from digest.planning import meta, snapshot
from digest.publish.files import create, destination
from digest.report.render_md import escape
from digest.util.proc import run


def render(value: dict[str, Any], config: Config) -> str:
    date = datetime.fromisoformat(value["created_at"]).astimezone(ZoneInfo(config.timezone))
    labels = {
        "save": "Ajuste guardado",
        "accept": "Propuesta aceptada",
        "dismiss": "Propuesta descartada",
    }
    lines = [
        "# Próximo foco · decisión del " + date.strftime("%d/%m/%Y"),
        labels[value["decision"]],
    ]
    for kind, label in (("mission", "Misión aceptada"), ("warmup", "Calentamientos aceptados")):
        lines.append("## " + label)
        selected = [i for i in value["active"] if i["kind"] == kind]
        if not selected:
            lines.append(
                "No se ha elegido una misión."
                if kind == "mission"
                else "No se han elegido calentamientos."
            )
        for item in selected:
            lines.extend(
                [
                    escape(item["action"]),
                    "Terminado cuando: " + escape(item["done_criterion"]),
                    "Dependencia: " + escape(item["dependency"] or "Ninguna declarada"),
                    "Motivo de la propuesta: "
                    + escape(item["proposal"]["reason"])
                    + " ["
                    + ", ".join(item["proposal"]["evidence"])
                    + "]",
                    "Origen: "
                    + escape(item["report_id"])
                    + (
                        "; ajustada por la persona."
                        if item["edited"]
                        else "; aceptada por la persona."
                    ),
                ]
            )
    changed = value["item"]
    lines.extend(
        [
            "## Elemento de esta decisión",
            escape(changed["action"]),
            "Terminado cuando: " + escape(changed["done_criterion"]),
            "Dependencia: " + escape(changed["dependency"] or "Ninguna declarada"),
            "## Procedencia",
            escape(value["id"]) + " · " + escape(value["created_at"]),
            "Informe de origen: " + escape(value["report_id"]),
            "Los ajustes humanos se conservan como texto humano; no son evidencia comprobada.",
        ]
    )
    return "\n\n".join(lines) + "\n"


def publish(
    db: sqlite3.Connection, config: Config, ident: str, *, channel: str | None = None
) -> dict[str, str]:
    if channel is not None and channel not in {"obsidian", "drive"}:
        raise ValueError("Unknown plan channel")
    value = snapshot(db, config, ident)
    directory = destination(config, Path(config.paths.data_dir), "plans/" + ident)
    create(directory / "plan.json", canonical(value).encode())
    create(directory / "plan.md", render(value, config).encode())
    date = datetime.fromisoformat(value["created_at"]).astimezone(ZoneInfo(config.timezone)).date()
    outcomes = {}
    selected = {channel} if channel else {"obsidian", "drive"}
    for channel in ("obsidian", "drive"):
        if channel not in selected:
            continue
        key = f"plan_delivery:{ident}:{channel}"
        prior = meta(db, key, {"state": "pending", "attempts": 0})
        if prior["state"] == "sent":
            outcomes[channel] = "sent"
            continue
        state = {
            "state": "pending",
            "attempts": prior["attempts"] + 1,
            "updated_at": utc(datetime.now(UTC)),
        }

        def save(delivery_key: str = key, delivery_state: dict[str, Any] = state) -> None:
            db.execute(
                "INSERT INTO meta(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (delivery_key, canonical(delivery_state)),
            )

        save()
        try:
            if channel == "obsidian":
                vault = Path(config.paths.obsidian_vault)
                lexical = vault / "Planes" / f"{date}-{ident}.md"
                if (vault / "Planes").is_symlink() or lexical.is_symlink():
                    raise ValueError("Plan notes cannot redirect to other vault notes")
                target = destination(config, vault, f"Planes/{date}-{ident}.md")
                create(target, (directory / "plan.md").read_bytes())
                remote = str(target)
            else:
                remote = config.drive.remote.rstrip("/") + "/plans/" + ident
                args = ["rclone"] + (
                    ["--config", "/dev/null"] if remote.startswith(":local:") else []
                )
                result = run(
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
                if result.returncode:
                    raise RuntimeError("Plan delivery failed")
            state.update(state="sent", remote_ref=remote)
        except (OSError, RuntimeError, ValueError):
            state.update(state="failed", error="plan_delivery_failed")
        save()
        outcomes[channel] = str(state["state"])
    return outcomes
