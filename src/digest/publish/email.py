"""Essential email with stable identity and conservative SMTP uncertainty."""

import smtplib
import ssl
from collections.abc import Callable
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, select_autoescape

from digest.config import Config
from digest.doctor import _credential
from digest.publish.files import create
from digest.report.model import Report, ResultEntry
from digest.report.timeutil import display

ENV = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
TEMPLATE = files("digest.report").joinpath("templates/email.html").read_text(encoding="utf-8")


def compose(
    config: Config, report: Report, directory: Path, drive_url: str | None = None
) -> EmailMessage:
    message = EmailMessage(policy=SMTP)
    message["Message-ID"] = f"<{report.id}@daily-digest.local>"
    message["Date"] = format_datetime(datetime.fromisoformat(report.created_at))
    message["From"] = config.email.from_address
    message["To"] = config.email.to
    message["Subject"] = "Daily Digest — " + display(report.end_at, report.timezone)
    groups: dict[str, list[ResultEntry]] = {}
    for item in report.results:
        groups.setdefault(item.project, []).append(item)
    warning = (
        "Hay cobertura incompleta; consulta el informe."
        if any(c.status != "ok" for c in report.coverage)
        else "Sin incidencias de captura registradas."
    )
    if any(
        o.get("origin") in {"initial_inventory", "historical_reference"}
        for o in report.observations.values()
    ):
        warning += " Incluye contexto histórico; no todo representa trabajo de hoy."
    plain = [
        "Daily Digest",
        display(report.end_at, report.timezone),
        "Informe completo disponible para revisar.",
    ]
    for project, items in groups.items():
        plain.append(project)
        plain.extend(
            f"{item.task_id or 'Fuera del tablero'} — {item.title.replace(chr(10), ' ')}"
            for item in items
        )
    if not report.results:
        plain.append("Sin resultados verificables; esto no demuestra que no se haya trabajado.")
    synthesis = report.sections.get("conceptual", {})
    plain.extend(
        c["text"] + " [" + ", ".join(c["evidence"]) + "]" for c in synthesis.get("highlights", [])
    )
    weekly = report.sections.get("weekly")
    if weekly:
        plain.append("Semana: patrones y propuesta")
        plain.extend(c["text"] + " [" + ", ".join(c["evidence"]) + "]" for c in weekly["patterns"])
        plain.extend(
            p["action"] + " — Terminado cuando: " + p["done_criterion"] for p in weekly["next_week"]
        )
    plan = report.sections.get("plan")
    if plan:
        plain.append("Plan de mañana")
        plain.extend(
            p["action"]
            + " — Terminado cuando: "
            + p["done_criterion"]
            + " — Motivo: "
            + p["reason"]
            + " — Origen: "
            + p["origin"]
            for p in [plan["mission"], *plan["warmups"]]
        )
    elif not weekly:
        plain.append("Plan de mañana: sin propuesta validada.")
    plain.append(warning)
    if drive_url:
        plain.append("Abrir informe completo en Drive: " + drive_url)
    selected = next(
        (item for item in report.results if item.review_state != "closed_by_human"), None
    )
    if selected:
        plain.append("Resultado para revisar: " + selected.title)
    images: list[dict[str, str]] = []
    attachments = []
    for item in report.results:
        for figure in item.figures:
            if len(images) >= 2:
                break
            path = (directory / figure.path).resolve()
            if not path.is_relative_to(directory.resolve()) or path.suffix != ".png":
                raise ValueError("Invalid inline figure")
            cid = f"figure{len(images) + 1}@daily-digest.local"
            images.append({"cid": cid, "caption": figure.caption})
            attachments.append((cid, path))
    message.set_content("\n".join(plain) + "\n")
    html = ENV.from_string(TEMPLATE).render(
        report=report,
        date=display(report.end_at, report.timezone),
        groups=groups,
        drive_url=drive_url,
        selected=selected,
        images=images,
        warning=warning,
    )
    message.add_alternative(html, subtype="html")
    alternative = message.get_payload(-1)
    assert isinstance(alternative, EmailMessage)
    for cid, path in attachments:
        alternative.add_related(
            path.read_bytes(),
            maintype="image",
            subtype="png",
            cid="<" + cid + ">",
            filename=path.name,
        )
    return message


def send(
    config: Config, message: EmailMessage, outbox: Path, update: Callable[[str, str | None], None]
) -> str:
    if outbox.exists():
        wire = outbox.read_bytes()
    else:
        wire = message.as_bytes()
        create(outbox, wire)
    password = _credential(config.email.password_env)
    if password is None:
        update("failed", "smtp_credential_missing")
        return "failed"
    smtp = None
    started = False
    try:
        smtp = smtplib.SMTP(config.email.smtp_host, config.email.smtp_port, timeout=30)
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(config.email.username, password)
        if smtp.mail(config.email.from_address)[0] != 250:
            raise smtplib.SMTPException("MAIL rejected")
        if smtp.rcpt(config.email.to)[0] not in {250, 251}:
            raise smtplib.SMTPException("RCPT rejected")
        # Persist uncertainty before DATA: a crash must never cause a blind resend.
        update("uncertain", "smtp_data_in_progress")
        started = True
        code, _ = smtp.data(wire)
        if code != 250:
            update("failed", "smtp_data_rejected")
            return "failed"
        update("sent", None)
        return "sent"
    except smtplib.SMTPDataError:
        update("failed", "smtp_data_rejected")
        return "failed"
    except (OSError, smtplib.SMTPException):
        state = "uncertain" if started else "failed"
        update(state, "smtp_confirmation_missing" if started else "smtp_failed")
        return state
    finally:
        if smtp is not None:
            smtp.close()
