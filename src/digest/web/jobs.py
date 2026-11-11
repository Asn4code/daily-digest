"""Bounded, public queue summaries; never expose raw job parameters or errors."""

import json
import sqlite3
from typing import Any

from digest import planning
from digest.collectors.base import canonical, content_hash
from digest.config import Config
from digest.report import inventory
from digest.web.store import Store

KINDS = {
    "daily": "Diario",
    "weekly": "Semanal",
    "preview": "Avance",
    "capture": "Captura",
    "contrast": "Contraste",
    "deliver": "Entrega",
    "backup": "Copia",
}
STATES = {
    "queued": "En cola",
    "running": "En curso",
    "done": "Terminado",
    "failed": "Necesita atención",
    "skipped": "Sin trabajo nuevo",
}
CHANNELS = {"obsidian": "Obsidian", "drive": "Drive", "email": "Correo"}
DELIVERY_STATES = {
    "pending": "Pendiente",
    "sent": "Entregado",
    "failed": "No completado",
    "uncertain": "Envío incierto",
}
STAGES = {
    "source": "Lectura de fuentes",
    "project": "Balance del proyecto",
    "conceptual": "Orientación",
    "plan": "Plan",
    "critical": "Crítica semanal",
    "weekly": "Síntesis semanal",
    "grounding": "Cotejo de fidelidad",
}


def summary(row: tuple[Any, ...]) -> dict[str, Any]:
    ident, kind, state, created, started, finished, requested, encoded = row
    params = json.loads(encoded)
    if not isinstance(params, dict):
        raise ValueError("Invalid job metadata")
    return {
        "id": ident,
        "kind": kind,
        "label": KINDS.get(kind, "Trabajo"),
        "state": state,
        "state_label": STATES.get(state, "No disponible"),
        "created_at": created,
        "started_at": started,
        "finished_at": finished,
        "requested_by": requested,
        "nodes": len(params.get("nodes", {})),
        "inventory": bool(params.get("inventory_hash")),
    }


SELECT = "SELECT id,kind,state,created_at,started_at,finished_at,requested_by,params FROM job "


def board(store: Store, page: int = 1) -> dict[str, Any]:
    if not 1 <= page <= 10000:
        raise ValueError("Invalid queue page")
    try:
        with store.database() as db:
            rows = db.execute(
                SELECT + "ORDER BY id DESC LIMIT 41 OFFSET ?", ((page - 1) * 40,)
            ).fetchall()
            counts = dict(db.execute("SELECT state,count(*) FROM job GROUP BY state"))
            latest = db.execute(
                "SELECT id FROM report WHERE status='ready' "
                "ORDER BY created_at DESC,id DESC LIMIT 1"
            ).fetchone()
    except (OSError, ValueError, sqlite3.Error):
        return {
            "jobs": [],
            "counts": {},
            "latest": None,
            "more": False,
            "available": False,
            "page": page,
        }
    ready = None
    if latest:
        try:
            document, _ = store.load(latest[0])
            ready = {
                "id": document.id,
                "kind": document.kind_label,
                "created_at": document.created_at,
            }
        except (OSError, ValueError, sqlite3.Error):
            pass
    return {
        "jobs": [summary(r) for r in rows[:40]],
        "counts": counts,
        "latest": ready,
        "more": len(rows) > 40,
        "available": True,
        "page": page,
    }


def detail(store: Store, config: Config, job_id: int, page: int = 1) -> dict[str, Any]:
    if job_id < 1 or not 1 <= page <= 10000:
        raise ValueError("Invalid job")
    with store.database() as db:
        row = db.execute(SELECT + "WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown job")
        result = summary(row)
        params = json.loads(row[-1])
        calls, successes = db.execute(
            "SELECT count(*),COALESCE(sum(ok),0) FROM llm_call WHERE job_id=?", (job_id,)
        ).fetchone()
        last = db.execute(
            "SELECT prompt_name FROM llm_call WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)
        ).fetchone()
        report_id = params.get("report_id") or params.get("report")
        deliveries = db.execute(
            "SELECT id,channel,state,attempts FROM delivery WHERE "
            + ("review_id=? " if params.get("review") else "report_id=? AND review_id IS NULL ")
            + "ORDER BY id LIMIT 100",
            (params.get("review") or report_id,),
        ).fetchall()
        ready = db.execute(
            "SELECT 1 FROM report WHERE interval_id=? AND status='ready' AND revision>?",
            (params.get("interval_id"), int(params.get("revision_after", 0))),
        ).fetchone()
        source = (
            db.execute(
                "SELECT id FROM job WHERE id!=? AND kind IN ('daily','weekly','preview') "
                "AND json_extract(params,'$.report_id')=? ORDER BY id DESC LIMIT 1",
                (job_id, report_id),
            ).fetchone()
            if report_id
            else None
        )
    result.update(
        calls=calls,
        successes=successes,
        stage=STAGES.get(last[0], "Generación")
        if last
        else "Recogida de evidencias"
        if result["state"] == "running"
        else None,
        deliveries=[
            {
                "id": r[0],
                "channel": r[1],
                "label": CHANNELS.get(r[1], "Canal"),
                "state": r[2],
                "state_label": DELIVERY_STATES.get(r[2], "No disponible"),
                "attempts": r[3],
            }
            for r in deliveries
        ],
        report=None,
        review=None,
        snapshot=None,
        resumable=result["state"] == "failed"
        and result["kind"] in {"daily", "weekly", "preview"}
        and bool(params.get("interval_id"))
        and not ready,
        inventory_items=[],
        inventory_count=0,
        inventory_more=False,
        inventory_page=page,
        parents=[{"id": source[0], "label": "Informe de origen"}] if source else [],
    )
    if report_id:
        try:
            document, _ = store.load(report_id)
            result["report"] = {"id": document.id, "label": document.kind_label}
        except (ValueError, OSError, sqlite3.Error):
            pass
    if params.get("plan"):
        with store.database() as db:
            value = planning.snapshot(db, config, params["plan"])
            result["snapshot"] = value["id"]
            result["deliveries"] = []
            for channel in ("obsidian", "drive"):
                state = planning.meta(
                    db,
                    f"plan_delivery:{value['id']}:{channel}",
                    {"state": "pending", "attempts": 0},
                )
                result["deliveries"].append(
                    {
                        "id": channel,
                        "channel": channel,
                        "label": CHANNELS[channel],
                        "state": state["state"],
                        "state_label": DELIVERY_STATES[state["state"]],
                        "attempts": state["attempts"],
                        "plan": value["id"],
                    }
                )
    if params.get("inventory_hash"):
        try:
            frozen = inventory.load(config, job_id, params["inventory_hash"])
            result.update(
                inventory_items=[
                    {"id": r.id, "title": r.title, "project": r.project}
                    for r in frozen.results[(page - 1) * 100 : page * 100]
                ],
                inventory_count=len(frozen.results),
                inventory_more=len(frozen.results) > page * 100,
            )
        except (ValueError, OSError):
            result["inventory_unavailable"] = True
    # Deliberate coarse graph: these are service stages, never model-chosen commands.
    stages = (
        ["Captura", "Fuentes", "Crítica", "Semanal", "Validación", "Entrega"]
        if result["kind"] == "weekly"
        else ["Captura", "Fuentes", "Balance", "Orientación", "Plan", "Validación", "Entrega"]
    )
    result["pipeline"] = stages if result["kind"] in {"daily", "weekly", "preview"} else []
    if result["kind"] == "preview" and result["pipeline"]:
        result["pipeline"] = stages[:-1]
    return result


def signature(value: dict[str, Any]) -> str:
    return content_hash(canonical(value))
