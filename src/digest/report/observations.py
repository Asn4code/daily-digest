"""Deterministic source observations, separate from scientific interpretations."""

import math
from typing import Any

from digest.report.model import EvidenceEntry

VERSION = "1"


def normalize(entry: EvidenceEntry) -> dict[str, Any]:
    origin = entry.meta.get("capture_origin", "observed_unknown_age")
    if entry.time_quality == "event" and entry.event_at:
        origin = "dated_event"
    computed = []
    if entry.kind == "metric":
        for operation in ("stats", "change"):
            values = entry.meta.get(operation, {})
            if not isinstance(values, dict):
                continue
            for column, statistics in sorted(values.items()):
                if not isinstance(statistics, dict):
                    continue
                for statistic, number in sorted(statistics.items()):
                    if type(number) in {int, float} and math.isfinite(number):
                        computed.append(
                            {
                                "column": column,
                                "statistic": statistic,
                                "operation": operation,
                                "value": number,
                                "unit": None,
                            }
                        )
    limitations = []
    if origin != "dated_event":
        limitations.append(
            "La hora de observación no acredita la fecha del trabajo ni de ejecución."
        )
    if origin == "initial_inventory":
        limitations.append("Referencia inicial: no se atribuye a trabajo de hoy.")
    if entry.kind == "metric":
        limitations.append("Estadísticos sobre columnas declaradas; unidades no declaradas.")
    if entry.kind == "notebook_change":
        limitations.append("Solo salidas almacenadas; el servicio no ejecutó el notebook.")
    if entry.kind == "agent_session":
        limitations.append("Texto de sesión; no acredita por sí solo la conclusión científica.")
    return {
        "version": VERSION,
        "evidence": [entry.id],
        "project_id": entry.project,
        "source_kind": entry.kind,
        "locator": entry.locator,
        "path": entry.meta.get("path"),
        "origin": origin,
        "observed_at": entry.observed_at,
        "event_at": entry.event_at,
        "time_quality": entry.time_quality,
        "computed": computed,
        "scientific_status": "source_observation",
        "limitations": limitations,
    }


def origin_label(origin: str) -> str:
    return {
        "initial_inventory": "Referencia inicial",
        "observed_change": "Cambio observado; fecha del trabajo no acreditada",
        "dated_event": "Evento con fecha propia",
    }.get(origin, "Observado; antigüedad desconocida")
