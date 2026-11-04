"""Command-line contracts; operations are implemented in subsequent tasks."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from digest.config import ConfigError, load_config
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


@app.command()
def capture(project: Annotated[str | None, typer.Option()] = None) -> None:
    """Capturar evidencias de los proyectos (pendiente: fase 1)."""
    pending("capture")


@app.command()
def run(
    weekly: Annotated[bool, typer.Option()] = False,
    preview: Annotated[bool, typer.Option()] = False,
    now: Annotated[bool, typer.Option()] = False,
    no_send: Annotated[bool, typer.Option("--no-send")] = False,
    since: Annotated[str | None, typer.Option()] = None,
    until: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Encolar o generar un informe (pendiente: fase 1)."""
    pending("run")


@app.command()
def enqueue(
    kind: str,
    requested_by: Annotated[str, typer.Option()] = "timer",
) -> None:
    """Encolar un trabajo (pendiente: fase 3)."""
    pending("enqueue")


@app.command()
def worker() -> None:
    """Procesar la cola de trabajos (pendiente: fase 3)."""
    pending("worker")


@app.command()
def web() -> None:
    """Arrancar la webapp local (pendiente: fase 3)."""
    pending("web")


@app.command()
def deliver(
    retry: Annotated[bool, typer.Option()] = False,
    channel: Annotated[str | None, typer.Option()] = None,
    force_uncertain: Annotated[bool, typer.Option()] = False,
) -> None:
    """Reintentar entregas (pendiente: fase 4)."""
    pending("deliver")


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
