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
from typing import Any

from jinja2 import Environment, select_autoescape

from digest.config import Config
from digest.doctor import _credential
from digest.llm.validator import validate_report
from digest.publish.files import create
from digest.report.completeness import require_complete
from digest.report.model import Report, ResultEntry
from digest.report.timeutil import display
from digest.report.views import CONFIDENCE, PRIORITIES, daily_view, weekly_checks, weekly_notices

ENV = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
TEMPLATE = files("digest.report").joinpath("templates/email.html").read_text(encoding="utf-8")


def compose(
    config: Config, report: Report, directory: Path, drive_url: str | None = None
) -> EmailMessage:
    validate_report(report, {e.id for e in report.evidence})
    require_complete(report)
    view = daily_view(report)
    message = EmailMessage(policy=SMTP)
    message["Message-ID"] = f"<{report.id}@daily-digest.local>"
    message["Date"] = format_datetime(datetime.fromisoformat(report.created_at))
    message["From"] = config.email.from_address
    message["To"] = config.email.to
    message["Subject"] = "Daily Digest — " + display(report.end_at, report.timezone)
    groups: dict[str, list[ResultEntry]] = {}
    for result in report.results:
        groups.setdefault(result.project, []).append(result)
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

    def cited(value: dict[str, Any]) -> str:
        return str(value["text"]) + " [" + ", ".join(value["evidence"]) + "]"

    plain = ["Daily Digest", display(report.end_at, report.timezone)]
    weekly = report.sections.get("weekly")
    critical = weekly_checks(report, highlighted=True)
    if weekly:
        if critical:
            for check in critical:
                plain.extend(
                    [
                        check["label"] + " · " + check["prior"]["project_id"],
                        "Interpretación (confianza "
                        + CONFIDENCE[check["assessment"]["confidence"]]
                        + "): "
                        + cited(check["assessment"]),
                        "Límite decisivo: " + cited(check["decisive_limit"]),
                        "Consecuencia para el foco: " + cited(check["focus_implication"]),
                    ]
                )
        else:
            plain.extend(cited(c) for c in weekly["patterns"][:3])
            plain.extend("Base del contraste: " + cited(c) for c in weekly_notices(report))
    else:
        for item in view.highlights:
            plain.extend(
                [
                    cited(item["observation"]),
                    "Interpretación (confianza "
                    + CONFIDENCE[item["meaning"]["confidence"]]
                    + "): "
                    + cited(item["meaning"]),
                    "Límite decisivo: " + cited(item["decisive_limit"]),
                ]
            )
    if not weekly and not view.highlights:
        plain.append(view.orientation_notice)
    plain.append("Propuesta de semana" if weekly else "Plan de mañana · próximo foco")
    if view.planning_for:
        plain.append("Orientado al " + view.planning_for + ". La elección sigue siendo tuya.")
    if view.accepted:
        plain.append("Plan aceptado: " + (view.accepted["edited_text"] or view.accepted["action"]))
        plain.append("Terminado cuando: " + view.accepted["done_criterion"])
        if view.accepted.get("dependency"):
            plain.append("Dependencia: " + view.accepted["dependency"])
        if view.carry_forward:
            plain.append("Se conserva el plan aceptado.")
    if view.change_reason:
        plain.append("Motivo para reconsiderar el foco: " + cited(view.change_reason))
    proposed = (
        weekly["next_week"] if weekly else ([view.mission] if view.mission else []) + view.warmups
    )
    for item in proposed:
        plain.extend(
            [
                "Propuesta: " + item["action"],
                "Terminado cuando: " + item["done_criterion"],
                "Dependencia: " + (item["dependency"] or "Ninguna declarada"),
                "Motivo: " + item["reason"] + " [" + ", ".join(item["evidence"]) + "]",
            ]
        )
        if item.get("priority_basis"):
            plain.append(
                "Prioridad por: " + ", ".join(PRIORITIES[b] for b in item["priority_basis"])
            )
        if item.get("decision_unlocked"):
            plain.append("Decisión que ayudaría a tomar: " + item["decision_unlocked"])
        if item.get("uncertainty_addressed"):
            plain.append("Duda o control: " + cited(item["uncertainty_addressed"]))
    if view.no_mission_reason:
        plain.append("Sin misión nueva propuesta: " + cited(view.no_mission_reason))
    elif not proposed and not view.carry_forward:
        plain.append("Sin misión nueva propuesta.")
    plain.append("Todo lo hecho y contexto observado")
    for project, items in groups.items():
        plain.append(project)
        plain.extend(
            f"{item.task_id or 'Fuera del tablero'} — {item.title.replace(chr(10), ' ')}"
            + (" (referencia inicial/histórica)" if item.reference_only else "")
            for item in items
        )
    if not report.results:
        plain.append("Sin resultados verificables; esto no demuestra que no se haya trabajado.")
    plain.append(warning)
    if drive_url:
        plain.append("Abrir informe completo en Drive: " + drive_url)
    candidate = report.sections.get("conceptual", {}).get("review_candidate")
    selected = next(
        (r for r in report.results if candidate and r.id == candidate["result_id"]), None
    )
    if selected is None:
        selected = next(
            (
                r
                for r in report.results
                if not r.reference_only and r.review_state != "closed_by_human"
            ),
            None,
        )
    if selected:
        plain.append("Resultado para revisar: " + selected.title)
    images: list[dict[str, str]] = []
    attachments = []
    for result in report.results:
        for figure in result.figures:
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
        view=view,
        confidence=CONFIDENCE,
        priorities=PRIORITIES,
        date=display(report.end_at, report.timezone),
        groups=groups,
        drive_url=drive_url,
        selected=selected,
        images=images,
        warning=warning,
        critical_highlights=critical,
        critical_notices=weekly_notices(report),
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
