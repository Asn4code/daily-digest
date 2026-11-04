"""Read-only diagnostics; online checks send synthetic data only."""

import http.client
import json
import os
import smtplib
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from digest.config import Config, ProviderConfig
from digest.util.fs import ReadError, read_bounded, safe_path
from digest.util.proc import ProcessError, run


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _credential(name: str) -> str | None:
    """Read named credentials without interpolation or logging."""
    if value := os.environ.get(name):
        return value
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not directory:
        return None
    try:
        path = Path(directory) / "secrets.env"
        with path.open(encoding="utf-8") as stream:
            content = stream.read(65537)
        if len(content) > 65536:
            return None
        for line in content.splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == name:
                return value.strip().strip("\"'") or None
    except (OSError, UnicodeError):
        return None
    return None


def _provider(provider: ProviderConfig) -> str:
    """Probe JSON-schema output using one small synthetic prompt."""
    key = _credential(provider.api_key_env)
    if key is None:
        return "credencial ausente"
    endpoint = urlsplit(provider.base_url)
    if endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username:
        return "URL del proveedor inválida"
    connection_type = (
        http.client.HTTPSConnection if endpoint.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(endpoint.hostname, endpoint.port, timeout=provider.timeout_s)
    payload = {
        "model": provider.model,
        "messages": [{"role": "user", "content": 'Devuelve solo el JSON {"ok": true}.'}],
        "max_tokens": 128,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "doctor",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
            },
        },
    }
    try:
        connection.request(
            "POST",
            endpoint.path.rstrip("/") + "/chat/completions",
            body=json.dumps(payload),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        response = connection.getresponse()
        if response.status != 200:
            return "petición sintética rechazada"
        content = response.read(65537)
        if len(content) > 65536:
            return "respuesta demasiado grande"
        parsed = json.loads(content)
        answer = json.loads(parsed["choices"][0]["message"]["content"])
        if not isinstance(answer, dict) or set(answer) != {"ok"} or answer["ok"] is not True:
            return "salida estructurada inválida"
        return ""
    except (OSError, ValueError, KeyError, IndexError, TypeError, http.client.HTTPException):
        return "falló la comprobación sintética"
    finally:
        connection.close()


def _smtp(config: Config) -> str:
    password = _credential(config.email.password_env)
    if password is None:
        return "credencial ausente"
    try:
        with smtplib.SMTP(config.email.smtp_host, config.email.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(config.email.username, password)
            if smtp.noop()[0] != 250:
                return "SMTP no confirma disponibilidad"
    except (OSError, smtplib.SMTPException):
        return "falló la comprobación SMTP"
    return ""


def _tool(name: str, args: list[str]) -> Check:
    try:
        result = run(args, timeout=15)
    except ProcessError:
        return Check(name, "error", "herramienta no disponible o timeout")
    return Check(
        name,
        "ok" if result.returncode == 0 else "error",
        "comprobación completada" if result.returncode == 0 else "comprobación fallida",
    )


def diagnose(config: Config, *, offline: bool = False) -> list[Check]:
    """Check paths and optionally services; never create data or send email."""
    checks = [Check("configuración", "ok", "YAML validado")]
    for name, directory in [
        ("datos", config.paths.data_dir),
        ("Obsidian", config.paths.obsidian_vault),
    ]:
        exists = Path(directory).is_dir()
        checks.append(
            Check(
                name,
                "ok" if exists else "error",
                "directorio existente" if exists else "directorio ausente",
            )
        )
    if not config.projects:
        checks.append(Check("proyectos", "aviso", "no hay proyectos configurados"))
    for index, project in enumerate(config.projects, 1):
        label = f"proyecto {index}"
        try:
            content = read_bounded(
                Path(project.root),
                project.kanvas,
                exclude=project.exclude,
                max_bytes=config.limits.max_file_bytes,
            )
            board = json.loads(content)
            if (
                not isinstance(board, dict)
                or type(board.get("kanvas")) is not int
                or board["kanvas"] != 1
            ):
                checks.append(Check(label, "error", "esquema Kanvas no compatible"))
                continue
            checks.append(Check(label, "ok", "tablero legible, esquema 1"))
            if not offline:
                path = safe_path(
                    Path(project.root),
                    project.kanvas,
                    exclude=project.exclude,
                    max_bytes=config.limits.max_file_bytes,
                )
                checks.append(
                    _tool(label + " kanvas check", [config.kanvas.cli, "check", "-b", str(path)])
                )
        except (ReadError, ValueError):
            checks.append(Check(label, "error", "tablero ausente, excluido o inválido"))
    if offline:
        checks.append(
            Check("servicios", "omitido", "modo offline: sin procesos ni peticiones de red")
        )
        return checks
    for index, provider in enumerate(config.llm.providers.values(), 1):
        started = time.monotonic()
        error = _provider(provider)
        elapsed = round((time.monotonic() - started) * 1000)
        checks.append(
            Check(
                f"LLM {index}",
                "error" if error else "ok",
                error or f"JSON sintético validado ({elapsed} ms)",
            )
        )
    error = _smtp(config)
    checks.append(Check("SMTP", "error" if error else "ok", error or "autenticado; sin envío"))
    checks.append(_tool("Drive", ["rclone", "lsd", config.drive.remote]))
    checks.append(_tool("Tailscale", ["tailscale", "serve", "status"]))
    return checks
