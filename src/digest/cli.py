"""Command-line contracts; operations are implemented in subsequent tasks."""

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from digest import worker as jobs
from digest.config import Config, ConfigError, load_config
from digest.doctor import diagnose

app = typer.Typer(help="Informes con evidencias y revisión personal.", no_args_is_help=True)


def pending(command: str) -> NoReturn:
    """Fail explicitly instead of claiming an operation succeeded."""
    typer.echo(
        f"{command}: pendiente de implementación; no se ha ejecutado ninguna acción.", err=True
    )
    raise typer.Exit(code=1)


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[Path | None, typer.Option(help="Archivo YAML de configuración.")] = None,
) -> None:
    """Keep the configuration path without reading it before validation exists."""
    ctx.obj = config


@app.command()
def doctor(
    ctx: typer.Context,
    offline: Annotated[bool, typer.Option(help="Validar rutas sin procesos ni red.")] = False,
) -> None:
    """Comprobar configuración, rutas y servicios sin enviar informes."""
    try:
        config = load_config(ctx.obj or Path("config.yaml"))
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None
    checks = diagnose(config, offline=offline)
    for check in checks:
        typer.echo(f"{check.status}: {check.name}: {check.detail}")
    raise typer.Exit(code=int(any(check.status == "error" for check in checks)))


def configuration(ctx: typer.Context) -> Config:
    try:
        return load_config(ctx.obj or Path("config.yaml"))
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None


def show_outcome(result: str | None) -> None:
    if result and Path(result).name == "draft.md":
        typer.echo("Generación pendiente; borrador conservado, sin entrega final.")
    typer.echo(result)


def submit(
    ctx: typer.Context,
    kind: str,
    params: dict[str, str | bool | None],
    *,
    now: bool = False,
    requested_by: str = "cli",
) -> None:
    config = configuration(ctx)
    try:
        ident = jobs.enqueue(config, kind, requested_by=requested_by, params=dict(params))
        typer.echo(f"Trabajo encolado: {ident}")
        if now:
            show_outcome(jobs.execute(config, ident))
    except (ValueError, OSError, RuntimeError, sqlite3.Error):
        typer.echo("No se pudo completar el trabajo; revisa configuración y registro.", err=True)
        raise typer.Exit(1) from None


@app.command()
def capture(ctx: typer.Context, project: Annotated[str | None, typer.Option()] = None) -> None:
    """Capturar evidencias de forma serializada."""
    submit(ctx, "capture", {"project": project}, now=True)


@app.command()
def run(
    ctx: typer.Context,
    weekly: Annotated[bool, typer.Option()] = False,
    preview: Annotated[bool, typer.Option()] = False,
    now: Annotated[bool, typer.Option()] = False,
    no_send: Annotated[bool, typer.Option("--no-send")] = False,
    since: Annotated[str | None, typer.Option()] = None,
    until: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Encolar un informe; --now lo procesa mediante el mismo worker."""
    if weekly and preview:
        raise typer.BadParameter("--weekly y --preview son excluyentes")
    for value in [since, until]:
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    raise ValueError
            except ValueError:
                raise typer.BadParameter("Las fechas deben ser ISO con zona horaria") from None
    if since and until and datetime.fromisoformat(since) >= datetime.fromisoformat(until):
        raise typer.BadParameter("--since debe preceder a --until")
    kind = "weekly" if weekly else "preview" if preview else "daily"
    submit(ctx, kind, {"since": since, "until": until, "no_send": no_send}, now=now)


@app.command()
def enqueue(
    ctx: typer.Context, kind: str, requested_by: Annotated[str, typer.Option()] = "timer"
) -> None:
    """Encolar sin ejecutar trabajo pesado."""
    if kind not in {"daily", "weekly", "capture", "backup"}:
        raise typer.BadParameter("Tipo de trabajo desconocido")
    if requested_by not in {"cli", "web", "timer"}:
        raise typer.BadParameter("Origen de trabajo desconocido")
    submit(ctx, kind, {}, requested_by=requested_by)


@app.command()
def resume(
    ctx: typer.Context,
    job: Annotated[int, typer.Argument(min=1)],
    now: Annotated[bool, typer.Option()] = False,
    no_send: Annotated[bool, typer.Option("--no-send")] = False,
) -> None:
    """Reanudar un trabajo pendiente en su ventana original, reutilizando piezas válidas."""
    config = configuration(ctx)
    try:
        jobs.resume(config, job, no_send=no_send)
        typer.echo(f"Trabajo reencolado: {job}")
        if now:
            show_outcome(jobs.execute(config, job))
    except (ValueError, OSError, RuntimeError, sqlite3.Error):
        typer.echo("No se pudo reanudar; comprueba el trabajo y su inventario.", err=True)
        raise typer.Exit(1) from None


@app.command()
def worker(ctx: typer.Context, once: Annotated[bool, typer.Option("--once")] = False) -> None:
    """Procesar la cola; --once procesa como máximo un trabajo."""
    config = configuration(ctx)
    jobs.recover(config)
    while True:
        result = jobs.execute(config)
        if result:
            show_outcome(result)
        if once:
            return
        if not result:
            time.sleep(1)


@app.command()
def web(ctx: typer.Context) -> None:
    """Arrancar la webapp local de lectura y revisión."""
    import uvicorn

    from digest.web.app import create_app

    config = configuration(ctx)
    uvicorn.run(
        create_app(config),
        host=config.web.bind,
        port=config.web.port,
        proxy_headers=False,
        access_log=False,
    )


@app.command()
def deliver(
    ctx: typer.Context,
    retry: Annotated[bool, typer.Option()] = False,
    channel: Annotated[str | None, typer.Option()] = None,
    force_uncertain: Annotated[bool, typer.Option()] = False,
    report: Annotated[str | None, typer.Option("--report")] = None,
) -> None:
    """Entregar un informe o reintentar canales pendientes y fallidos."""
    if not retry and report is None:
        raise typer.BadParameter("Indica --retry o --report ID")
    if channel is not None and channel not in {"email", "obsidian", "drive"}:
        raise typer.BadParameter("Canal desconocido")
    submit(
        ctx,
        "deliver",
        {"channel": channel, "report": report, "force_uncertain": force_uncertain},
        now=True,
    )


@app.command()
def backup() -> None:
    """Crear una copia consistente (pendiente: fase 4)."""
    pending("backup")


@app.command()
def restore(source: Annotated[Path, typer.Option("--from")]) -> None:
    """Restaurar desde una copia (pendiente: fase 4)."""
    pending("restore")


@app.command()
def brief(
    kind: str,
    result_id: str,
    zip_output: Annotated[bool, typer.Option("--zip")] = False,
) -> None:
    """Crear un brief de un resultado revisado (pendiente: fase 6)."""
    pending("brief")


@app.command()
def extensions() -> None:
    """Listar extensiones (pendiente: fase 6)."""
    pending("extensions")


@app.command()
def mcp() -> None:
    """Servir herramientas de lectura (pendiente: fase 6)."""
    pending("mcp")
