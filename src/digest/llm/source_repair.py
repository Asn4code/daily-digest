"""Scoped claim-level repair plans for SourceFindings validation errors."""

import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, create_model

from digest.collectors.base import canonical, content_hash
from digest.llm import schemas
from digest.llm.client import json_object
from digest.llm.contracts import MAX_SCHEMA_CHARS, evidence_schema
from digest.llm.diagnostics import validation_issue
from digest.llm.quantities import Quantity, quantities, view
from digest.llm.validator import (
    GIT_IDENTITY,
    ISO_TIMESTAMP,
    SPANISH_DATE,
    ValidationError,
    _numeric_values,
)

CLAIM_LISTS = ("observations", "interpretations", "controls", "limitations", "open_questions")
HTML_PATTERN = re.compile(r"<\s*/?\s*[A-Za-z!]")
ClaimPath = tuple[str] | tuple[str, int]


@dataclass(frozen=True)
class RepairTarget:
    """Single rejected claim bound to an immutable candidate and path."""

    id: str
    path: ClaimPath
    field: str
    is_interpretation: bool
    issues: list[dict[str, str]]
    required_values: tuple[float, ...] = ()
    requires_quantity: bool = False


@dataclass(frozen=True)
class SourceRepairPlan:
    """Closed-target patch contract and reconstruction helper for SourceFindings."""

    candidate: dict[str, Any]
    candidate_hash: str
    targets: dict[str, RepairTarget]
    model: type[BaseModel]
    schema: dict[str, Any]
    messages: list[dict[str, str]]

    def compact_messages(self) -> list[dict[str, str]]:
        """Factor repeated diagnostics without dropping target claims or numbers."""
        rules = sorted(
            {issue["rule"] for target in self.targets.values() for issue in target.issues}
        )
        codes = {rule: chr(ord("a") + index) for index, rule in enumerate(rules)}
        targets: dict[str, Any] = {}
        for tid, target in self.targets.items():
            claim = (
                self.candidate["summary"]
                if len(target.path) == 1
                else self.candidate[target.path[0]][target.path[1]]
            )
            targets[tid] = {
                "original": _blank_html(deepcopy(claim)),
                "issues": [[codes[i["rule"]], i["field"]] for i in target.issues],
                **(
                    {
                        "preserve_numbers": [
                            int(v) if v.is_integer() else v for v in target.required_values
                        ]
                    }
                    if target.required_values
                    else {}
                ),
            }
        context = {
            "format": "source_claim_repair_compact_v1",
            "rules": {code: rule for rule, code in codes.items()},
            "targets": targets,
        }
        return [
            {"role": "assistant", "content": canonical(context)},
            {
                "role": "user",
                "content": (
                    "Devuelve solo SourceClaimRepair: objeto con exactamente los IDs de targets; "
                    "cada valor es original corregido conforme a issues (código en rules). "
                    "Mantén preserve_numbers y las reglas de fuente del sistema. "
                    "No modifiques otras afirmaciones."
                ),
            },
        ]

    def apply(self, patch: Any) -> dict[str, Any]:
        """Validate a scoped patch and substitute only its bound targets."""
        payload = json_object(patch) if isinstance(patch, str) else patch
        parsed = self.model.model_validate(payload)
        reconstructed = deepcopy(self.candidate)
        for tid, target in self.targets.items():
            claim_dump = getattr(parsed, tid).model_dump()
            patched_qs = _claim_quantities(claim_dump["text"])
            if target.requires_quantity and not patched_qs:
                raise ValidationError("unsupported_number", (*target.path, "text"))
            for req_val in target.required_values:
                if not any(
                    math.isclose(req_val, pq.value, rel_tol=1e-6, abs_tol=0) for pq in patched_qs
                ):
                    raise ValidationError("unsupported_number", (*target.path, "text"))
            if len(target.path) == 1:
                reconstructed["summary"] = claim_dump
            else:
                section, index = target.path
                reconstructed[section][index] = claim_dump
        return reconstructed


def _claim_quantities(text: str) -> list[Quantity]:
    cleaned = view(text)
    cleaned = GIT_IDENTITY.sub(" ", cleaned)
    cleaned = ISO_TIMESTAMP.sub(" ", cleaned)
    cleaned = SPANISH_DATE.sub(" ", cleaned)
    cleaned = re.sub(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", " ", cleaned)
    cleaned = re.sub(r"(?<!\d)\d{2}:\d{2}(?::\d{2})?(?!\d)", " ", cleaned)
    return [q for q in quantities(cleaned) if q.valid]


def _source_numbers(
    package: dict[str, Any] | None, cited_ids: set[str] | None = None
) -> list[float]:
    if not isinstance(package, dict):
        return []
    entries = package.get("evidence")
    if not isinstance(entries, list):
        return []
    values: list[float] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if cited_ids is not None and entry.get("id") not in cited_ids:
            continue
        if entry.get("kind") == "metric":
            meta = entry.get("meta")
            if isinstance(meta, dict):
                values.extend(_numeric_values([meta.get("stats", {}), meta.get("change", {})]))
        excerpt = entry.get("excerpt")
        if isinstance(excerpt, str):
            source = view(excerpt)
            if not any(marker in source for marker in ("PDBTOKEN", "SOURCEREFERENCE", "OPAQUEREF")):
                values.extend(q.value for q in _claim_quantities(excerpt))
    return values


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _blank_html(value: Any) -> Any:
    if isinstance(value, str):
        return "" if HTML_PATTERN.search(value) else value
    if isinstance(value, list):
        return [_blank_html(item) for item in value]
    if isinstance(value, dict):
        return {key: _blank_html(item) for key, item in value.items()}
    return value


def _claim_path(path: tuple[str | int, ...], candidate: dict[str, Any]) -> ClaimPath | None:
    if not path:
        return None
    if path[0] == "summary":
        if len(path) > 3:
            return None
        if len(path) >= 2 and path[1] not in {"text", "evidence"}:
            return None
        if len(path) == 3:
            refs = candidate.get("summary", {}).get("evidence", [])
            if path[1] != "evidence" or not _is_plain_int(path[2]):
                return None
            ev_index = path[2]
            if not isinstance(ev_index, int) or not (0 <= ev_index < len(refs)):
                return None
        return ("summary",)
    section = path[0]
    if isinstance(section, str) and section in CLAIM_LISTS and len(path) >= 2:
        index = path[1]
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        items = candidate.get(section)
        if not isinstance(items, list) or not (0 <= index < len(items)):
            return None
        if len(path) > 4:
            return None
        allowed = (
            {"text", "evidence", "confidence"}
            if section == "interpretations"
            else {"text", "evidence"}
        )
        if len(path) >= 3 and path[2] not in allowed:
            return None
        if len(path) == 4:
            refs = items[index].get("evidence", [])
            if path[2] != "evidence" or not _is_plain_int(path[3]):
                return None
            ev_index = path[3]
            if not isinstance(ev_index, int) or not (0 <= ev_index < len(refs)):
                return None
        return (section, index)
    return None


def _extract_evidence_enum(schema: dict[str, Any]) -> set[str] | None:
    def walk(value: Any) -> set[str] | None:
        if isinstance(value, dict):
            for name, prop in value.get("properties", {}).items():
                if name == "evidence" and isinstance(prop, dict):
                    target = prop.get("items", {}) if prop.get("type") == "array" else prop
                    if isinstance(target, dict) and isinstance(target.get("enum"), list):
                        return {str(item) for item in target["enum"]}
            for child in value.values():
                found = walk(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found is not None:
                    return found
        return None

    return walk(schema)


def plan_source_repair(
    candidate_raw: Any,
    error: ValueError,
    schema: dict[str, Any] | None,
    *,
    package: dict[str, Any] | None = None,
    max_schema_chars: int | None = None,
) -> SourceRepairPlan | None:
    """Build a scoped claim repair plan when every error localizes to a SourceFindings claim."""
    if schema is None or schema.get("title") != "SourceFindings":
        return None
    if not isinstance(error, ValidationError):
        return None
    try:
        parsed = schemas.SourceFindings.model_validate(candidate_raw)
    except ValueError:
        return None
    candidate = parsed.model_dump()
    candidate_hash = content_hash(canonical(candidate))
    errors = (error, *error.related)[:20]
    if not errors:
        return None
    grouped: dict[ClaimPath, list[dict[str, str]]] = {}
    all_issues: list[dict[str, str]] = []
    for item in errors:
        claim_path = _claim_path(item.path, candidate)
        diag = validation_issue(item, schema)
        if claim_path is None or diag["field"] == "$" or "<extra>" in diag["field"]:
            return None
        issue_entry = {"rule": diag["rule"], "field": diag["field"]}
        grouped.setdefault(claim_path, []).append(issue_entry)
        all_issues.append(issue_entry)

    def target_payload(path: ClaimPath) -> Any:
        if len(path) == 1:
            return candidate["summary"]
        section, index = path
        return candidate[section][index]

    targets: dict[str, RepairTarget] = {}
    for claim_path, issues in grouped.items():
        tid = (
            "claim_"
            + content_hash(canonical({"candidate": candidate_hash, "path": list(claim_path)}))[:12]
        )
        field = "summary" if len(claim_path) == 1 else f"{claim_path[0]}.{claim_path[1]}"
        req_vals: list[float] = []
        requires_quantity = False
        if any(issue["rule"] == "unsupported_number" for issue in issues):
            claim_obj = target_payload(claim_path)
            cited = {str(ref) for ref in claim_obj.get("evidence", [])}
            source_numbers = _source_numbers(package, cited_ids=cited)
            orig_qs = _claim_quantities(str(claim_obj["text"]))
            for q in orig_qs:
                if any(
                    math.isclose(q.value, sv, rel_tol=1e-6, abs_tol=0) for sv in source_numbers
                ) and not any(math.isclose(q.value, r, rel_tol=1e-6, abs_tol=0) for r in req_vals):
                    req_vals.append(q.value)
            requires_quantity = bool(req_vals)
        targets[tid] = RepairTarget(
            id=tid,
            path=claim_path,
            field=field,
            is_interpretation=claim_path[0] == "interpretations",
            issues=issues,
            required_values=tuple(req_vals),
            requires_quantity=requires_quantity,
        )
    fields: dict[str, Any] = {
        tid: (schemas.Interpretation if target.is_interpretation else schemas.Claim, ...)
        for tid, target in targets.items()
    }
    repair_model: type[BaseModel] = create_model(
        "SourceClaimRepair", __base__=schemas.Output, **fields
    )
    allowed_refs = _extract_evidence_enum(schema)
    schema_limit = (
        min(MAX_SCHEMA_CHARS, max_schema_chars)
        if max_schema_chars is not None
        else MAX_SCHEMA_CHARS
    )
    try:
        repair_schema = (
            evidence_schema(repair_model, allowed_refs, max_chars=schema_limit)
            if allowed_refs is not None
            else repair_model.model_json_schema()
        )
    except ValueError:
        return None
    if len(json.dumps(repair_schema, ensure_ascii=False)) > schema_limit:
        return None

    wire_targets = {
        tid: _blank_html(deepcopy(target_payload(target.path))) for tid, target in targets.items()
    }
    first = all_issues[0]
    targets_payload = [
        {
            "id": target.id,
            "field": target.field,
            "kind": "Interpretation" if target.is_interpretation else "Claim",
            "issues": target.issues,
            **(
                {
                    "preserve_numbers": [
                        int(v) if v.is_integer() else v for v in target.required_values
                    ]
                }
                if target.required_values
                else {}
            ),
        }
        for target in targets.values()
    ]
    rules = {issue["rule"] for issue in all_issues}
    prompt_text = (
        "Repara solo las afirmaciones rechazadas de SourceFindings: devuelve un objeto JSON "
        "con exactamente los IDs de objetivo solicitados y la afirmación completa corregida "
        "(text, evidence y, en interpretations, confidence). "
        "No añadas otros campos ni modifiques el resto de la fuente. "
        "Usa referencias y cifras de las evidencias originales sin HTML ni marcadores de "
        "nombre entre ángulos; describe su función sin inventar un archivo. "
        "Error de validación: "
        + first["rule"]
        + "; campo: "
        + first["field"]
        + (
            ". Revisa todos estos campos en la misma reparación: " + canonical(all_issues)
            if len(all_issues) > 1
            else ""
        )
        + ". Objetivos a reparar: "
        + canonical(targets_payload)
        + (
            ". Prohibido eliminar cifras, recuentos por modelo o comparaciones de longitud de "
            "la afirmación original para eludir la validación: conserva todos los valores de "
            "preserve_numbers respetando literalmente cuándo llevan unidad o etiqueta y cuándo "
            "van solos en la fuente (p. ej. «4 secuencias», pero «3 partial» o «rfaa 29» sin "
            "añadir «secuencias»), citando completo el paréntesis que siga a la cifra "
            "(p. ej. «33 (las 29 de ...)») y poniendo coma tras «)» o «» antes de cualquier "
            "palabra siguiente (incluidos verbos o «no», p. ej. «206 de 206 (...)», no "
            "implican). No atribuyas causa ni vía a una fila con «0» o «—». "
            "Cada cifra se comprueba solo contra los IDs citados en ese campo. "
            "Si procede de otra evidencia del paquete, cita su ID exacto; no cambies el valor. "
            "Conserva unidades y etiquetas literales, el paréntesis completo que acompañe a una "
            "cifra y su texto tras dos puntos. Si citas una cantidad o razón entre comillas "
            "(como «206 de 206 (...)»), incluye su paréntesis completo y separa la prosa con "
            "coma o punto y coma antes de la palabra siguiente para que no se lea como unidad. "
            "No coloques verbos ni sustantivos inmediatamente detrás de un número sin unidad "
            "en la fuente (separa con coma, p. ej. «apartado 3, que...»). "
            "No transcribas identificadores técnicos con dígitos unidos por guion bajo "
            "(como códigos SRR con «_»); descríbelos por su función técnica. "
            "No ocultes unidades ni escribas cifras con palabras para eludir la comprobación."
            if "unsupported_number" in rules
            else ""
        )
        + (
            ". No uses etiquetas HTML ni marcadores de nombre entre ángulos. "
            "Si la fuente contiene un nombre provisional con ese marcador, describe su función "
            "sin reproducirlo; no inventes otro archivo."
            if "html_forbidden" in rules
            else ""
        )
    )
    plan_messages = [
        {"role": "assistant", "content": canonical(wire_targets)},
        {"role": "user", "content": prompt_text},
    ]
    return SourceRepairPlan(
        candidate=candidate,
        candidate_hash=candidate_hash,
        targets=targets,
        model=repair_model,
        schema=repair_schema,
        messages=plan_messages,
    )
