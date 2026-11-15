"""Immutable follow-up artifacts and independent, conservative channel deliveries."""

import base64
import json
import sqlite3
from datetime import UTC, datetime
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import SMTP
from email.utils import format_datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, select_autoescape

from digest.collectors.base import canonical, content_hash, utc
from digest.config import Config
from digest.followups import records
from digest.followups.generate import read_revision
from digest.publish import email
from digest.publish.files import create, destination
from digest.report.pdf import render_bytes as pdf_bytes
from digest.report.render_md import claim, escape, interpretation
from digest.util.fs import read_bounded
from digest.util.proc import run
from digest.util.redact import known_secrets, redact_tree

CHANNELS = ("obsidian", "drive", "email")
STATUS = {
    "reproduced": "Cálculo registrado reproducido",
    "discrepancy": "Discrepancia sobre los mismos datos",
    "changed_data": "Los datos actuales han cambiado",
    "not_verifiable": "No verificable con esta comprobación",
}
ENV = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
HTML = files("digest.report").joinpath("templates/followup.html").read_text(encoding="utf-8")


def directory(config: Config, ident: str, revision: int) -> Path:
    if (
        not records.IDENTIFIER.fullmatch(ident)
        or type(revision) is not int
        or not 1 <= revision <= 100000
    ):
        raise ValueError("Invalid follow-up destination")
    base = Path(config.paths.data_dir).resolve()
    relative = f"followups/{ident}/r{revision}"
    part = base
    for component in Path(relative).parts:
        part = part / component
        if part.is_symlink():
            raise ValueError("Follow-up output cannot redirect")
    return destination(config, base, relative)


def render_md(value: dict[str, Any], config: Config) -> str:
    context, answer = value["package"]["context"], value["answer"]
    lines = [
        "# Ampliación del diario",
        "Cobertura parcial: solo las frases solicitadas. El original conserva todo lo hecho.",
        "Informe original: "
        + escape(value["source_id"])
        + " · revisión "
        + str(value["source_revision"]),
        "Abrir original: "
        + config.web.public_base_url.rstrip("/")
        + "/reports/"
        + value["source_id"],
        "## Frases y pregunta",
    ]
    for selected in context["selections"]:
        lines.append(escape(selected["text"]) + " [" + ", ".join(selected["evidence"]) + "]")
    lines.extend(
        ["Pregunta de la persona: " + escape(context["question"]), "## Explicación ampliada"]
    )
    lines.extend(claim(c) for c in answer["explanation"])
    lines.append("## Qué se comprobó")
    for receipt in context["checks"]:
        lines.extend(
            [
                "### " + STATUS[receipt["status"]],
                escape(receipt["method"])
                + " · "
                + escape(receipt["checked_at"])
                + " ["
                + receipt["evidence_id"]
                + "]",
                "\n".join(
                    "    " + line
                    for line in json.dumps(receipt, ensure_ascii=False, indent=2).splitlines()
                ),
            ]
        )
    if not context["checks"]:
        lines.append(
            "Se pidió una explicación. No se realizaron comprobaciones nuevas "
            "sobre archivos del proyecto."
        )
    lines.extend(["## Interpretación y límites", interpretation(answer["interpretation"])])
    lines.extend(claim(c) for c in answer["limits"])
    lines.extend("Información pendiente: " + claim(c) for c in answer["missing_information"])
    if answer["focus_proposal"]:
        lines.extend(["## Propuesta para considerar", claim(answer["focus_proposal"])])
    lines.extend(
        [
            "No se cambia ninguna misión ni estado humano por solicitar esta ampliación.",
            "## Evidencias y procedencia",
        ]
    )
    for entry in value["package"]["evidence"]:
        lines.extend(
            [
                "### " + entry["id"],
                escape(entry["kind"] + " · " + entry["locator"]),
                escape(entry["excerpt"]),
            ]
        )
    lines.append(
        escape(value["id"])
        + " · revisión "
        + str(value["revision"])
        + " · "
        + escape(value["created_at"])
    )
    return "\n\n".join(lines) + "\n"


def artifacts(db: sqlite3.Connection, config: Config, value: dict[str, Any]) -> Path:
    root = directory(config, value["id"], value["revision"])
    names = ("followup.json", "followup.md", "followup.html", "followup.pdf")
    if any((root / name).is_symlink() for name in names):
        raise ValueError("Follow-up artifact cannot redirect")
    key = f"followup_artifacts:{value['id']}:r{value['revision']}"
    if records.meta(db, key) is not None:
        hashes = {
            name: content_hash(read_bounded(root, name, max_bytes=4_000_000)) for name in names
        }
        if records.verified(db, key) != hashes:
            raise ValueError("Follow-up artifact changed")
        return root
    clean = redact_tree(value, known_secrets(config))
    markup = ENV.from_string(HTML).render(
        value=clean,
        context=clean["package"]["context"],
        status=STATUS,
        original_url=config.web.public_base_url.rstrip("/") + "/reports/" + value["source_id"],
    )
    payloads = {
        "followup.json": canonical(clean).encode(),
        "followup.md": render_md(clean, config).encode(),
        "followup.html": markup.encode(),
    }
    for name, raw in payloads.items():
        create(root / name, raw)
    pdf_key = f"followup_pdf:{value['id']}:r{value['revision']}"
    if records.meta(db, pdf_key) is None:
        raw_pdf = pdf_bytes(root, markup)
        records.immutable(
            db,
            pdf_key,
            {
                "revision_hash": content_hash(canonical(value)),
                "html_hash": content_hash(markup),
                "pdf_hash": content_hash(raw_pdf),
                "pdf": base64.b64encode(raw_pdf).decode("ascii"),
            },
        )
    bound_pdf = records.verified(db, pdf_key)
    raw_pdf = base64.b64decode(bound_pdf["pdf"], validate=True)
    if (
        bound_pdf["revision_hash"] != content_hash(canonical(value))
        or bound_pdf["html_hash"] != content_hash(markup)
        or bound_pdf["pdf_hash"] != content_hash(raw_pdf)
    ):
        raise ValueError("Follow-up PDF binding changed")
    create(root / "followup.pdf", raw_pdf)
    payloads["followup.pdf"] = raw_pdf
    hashes = {name: content_hash(read_bounded(root, name, max_bytes=4_000_000)) for name in names}
    if hashes != {name: content_hash(raw) for name, raw in payloads.items()}:
        raise ValueError("Follow-up artifact changed before certification")
    records.immutable(db, key, hashes)
    return root


def publish(
    db: sqlite3.Connection, config: Config, ident: str, revision: int, *, channel: str | None = None
) -> dict[str, str]:
    if channel is not None and channel not in CHANNELS:
        raise ValueError("Unknown follow-up channel")
    value = read_revision(db, config, ident, revision)
    root = artifacts(db, config, value)
    outcomes = {}
    for name in CHANNELS:
        if channel and channel != name:
            continue
        key = f"followup_delivery:{ident}:r{revision}:{name}"
        prior = records.meta(db, key, {"state": "pending", "attempts": 0})
        if prior["state"] in {"sent", "uncertain"}:
            outcomes[name] = prior["state"]
            continue
        saved = {
            **prior,
            "state": "pending",
            "attempts": prior["attempts"] + 1,
            "updated_at": utc(datetime.now(UTC)),
        }
        records.state(db, key, saved)

        def update(
            state: str,
            error: str | None = None,
            delivery_key: str = key,
            delivery: dict[str, Any] = saved,
        ) -> None:
            delivery.update(state=state, error=error, updated_at=utc(datetime.now(UTC)))
            records.state(db, delivery_key, delivery)

        try:
            if name == "obsidian":
                vault = Path(config.paths.obsidian_vault)
                date = (
                    datetime.fromisoformat(value["created_at"])
                    .astimezone(ZoneInfo(config.timezone))
                    .date()
                )
                relative = f"Ampliaciones/{date}-{ident}-r{revision}.md"
                if (vault / "Ampliaciones").is_symlink() or (vault / relative).is_symlink():
                    raise ValueError("Follow-up note cannot redirect")
                target = destination(config, vault, relative)
                create(target, read_bounded(root, "followup.md", max_bytes=4_000_000))
                update("sent")
            elif name == "drive":
                remote = config.drive.remote.rstrip("/") + f"/followups/{ident}/r{revision}"
                args = ["rclone"] + (
                    ["--config", "/dev/null"] if remote.startswith(":local:") else []
                )
                result = run(
                    [
                        *args,
                        "copy",
                        "--immutable",
                        "--include",
                        "followup.json",
                        "--include",
                        "followup.md",
                        "--include",
                        "followup.pdf",
                        "--retries",
                        "1",
                        "--low-level-retries",
                        "1",
                        str(root),
                        remote,
                    ],
                    timeout=300,
                )
                if result.returncode:
                    raise RuntimeError("Follow-up delivery failed")
                update("sent")
            else:
                message_id = f"<{ident}-r{revision}@daily-digest.local>"
                data = Path(config.paths.data_dir).resolve()
                lexical = data / "outbox" / f"{ident}-r{revision}.eml"
                if (data / "outbox").is_symlink() or lexical.is_symlink():
                    raise ValueError("Outbox cannot redirect")
                outbox = destination(config, data, f"outbox/{ident}-r{revision}.eml")
                binding_key = f"followup_mail:{ident}:r{revision}"
                if records.meta(db, binding_key) is None:
                    if outbox.exists():
                        raise ValueError("Unbound follow-up outbox")
                    message = EmailMessage(policy=SMTP)
                    message["Message-ID"], message["From"], message["To"] = (
                        message_id,
                        config.email.from_address,
                        config.email.to,
                    )
                    message["Date"] = format_datetime(datetime.fromisoformat(value["created_at"]))
                    message["Subject"] = "Daily Digest — ampliación solicitada"
                    message.set_content(
                        "Ampliación solicitada\n"
                        + config.web.public_base_url.rstrip("/")
                        + f"/followups/{ident}/r{revision}\n\n"
                        + read_bounded(root, "followup.md", max_bytes=4_000_000).decode()
                    )
                    message.add_alternative(
                        read_bounded(root, "followup.html", max_bytes=4_000_000).decode(),
                        subtype="html",
                    )
                    wire = message.as_bytes()
                    records.immutable(
                        db,
                        binding_key,
                        {
                            "revision_hash": content_hash(canonical(value)),
                            "wire_hash": content_hash(wire),
                            "wire": base64.b64encode(wire).decode("ascii"),
                        },
                    )
                binding = records.verified(db, binding_key)
                wire = base64.b64decode(binding["wire"], validate=True)
                if (
                    binding["revision_hash"] != content_hash(canonical(value))
                    or content_hash(wire) != binding["wire_hash"]
                ):
                    raise ValueError("Follow-up wire binding changed")
                create(outbox, wire)
                message = BytesParser(policy=SMTP).parsebytes(wire)
                if not isinstance(message, EmailMessage):
                    raise ValueError("Invalid follow-up outbox")
                if (
                    str(message["Message-ID"]) != message_id
                    or str(message["To"]) != config.email.to
                    or str(message["From"]) != config.email.from_address
                ):
                    raise ValueError("Follow-up mail identity changed")
                outcomes[name] = email.send(
                    config, message, outbox, update, expected_hash=binding["wire_hash"]
                )
                continue
            outcomes[name] = "sent"
        except (OSError, ValueError, RuntimeError):
            update("failed", "followup_delivery_failed")
            outcomes[name] = "failed"
    return outcomes
