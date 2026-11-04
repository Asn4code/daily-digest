"""Strict configuration loading without resolving or exposing credentials."""

import re
from pathlib import Path
from typing import Annotated, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

PositiveInt = Annotated[int, Field(gt=0)]
Text = Annotated[str, Field(min_length=1)]
EnvName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]


class ConfigError(ValueError):
    """A configuration problem with no raw input in the message."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class ScheduleConfig(StrictModel):
    daily: str = "20:00"
    weekly: str = "Sat 10:00"
    capture_every_hours: PositiveInt = 2
    max_generation_minutes: PositiveInt = 60

    @field_validator("daily", "weekly")
    @classmethod
    def valid_schedule(cls, value: str) -> str:
        if not re.fullmatch(
            r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) )?(?:[01]\d|2[0-3]):[0-5]\d", value
        ):
            raise ValueError("hora inválida")
        return value

    @model_validator(mode="after")
    def schedule_shape(self) -> Self:
        if " " in self.daily or " " not in self.weekly:
            raise ValueError("daily requiere HH:MM; weekly requiere día HH:MM")
        return self


class PathsConfig(StrictModel):
    data_dir: Text
    obsidian_vault: Text
    obsidian_digest_dir: Text = "Digest"
    obsidian_reviews_dir: Text = "Revisiones"
    obsidian_briefs_dir: Text = "Briefs"

    @field_validator("data_dir", "obsidian_vault")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("se requiere una ruta absoluta")
        return value

    @field_validator("obsidian_digest_dir", "obsidian_reviews_dir", "obsidian_briefs_dir")
    @classmethod
    def relative_directory(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("se requiere una subcarpeta relativa")
        return value


class MetricConfig(StrictModel):
    label: Text
    pattern: Text
    columns: Annotated[list[Text], Field(min_length=1)]


class SlurmConfig(StrictModel):
    enabled: bool = False
    user: str = ""

    @model_validator(mode="after")
    def enabled_user(self) -> Self:
        if self.enabled and not self.user:
            raise ValueError("Slurm habilitado requiere user")
        return self


class RunsConfig(StrictModel):
    slurm: SlurmConfig = Field(default_factory=SlurmConfig)
    logs: list[Text] = Field(default_factory=list)


class ProjectConfig(StrictModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
    name: Text
    root: Text
    objective: str = ""
    priority: PositiveInt = 1
    external_allowed: bool = True
    kanvas: Text = "kanvas.json"
    include: list[Text] = Field(default_factory=list)
    exclude: list[Text] = Field(default_factory=list)
    figures: list[Text] = Field(default_factory=list)
    metrics: list[MetricConfig] = Field(default_factory=list)
    runs: RunsConfig = Field(default_factory=RunsConfig)
    agent_sessions: list[Text] = Field(default_factory=list)

    @field_validator("root")
    @classmethod
    def absolute_root(cls, value: str) -> str:
        return PathsConfig.absolute_path(value)

    @field_validator("kanvas")
    @classmethod
    def relative_board(cls, value: str) -> str:
        return PathsConfig.relative_directory(value)


class LimitsConfig(StrictModel):
    max_file_bytes: PositiveInt = 2_000_000
    max_excerpt_chars: PositiveInt = 4000
    max_diff_chars_per_file: PositiveInt = 6000
    max_project_package_chars: PositiveInt = 200_000
    capture_timeout_seconds: PositiveInt = 300


class ProviderConfig(StrictModel):
    base_url: Text
    model: Text
    api_key_env: EnvName
    timeout_s: PositiveInt = 180

    @field_validator("base_url")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        try:
            endpoint = urlsplit(value)
            port = endpoint.port
            if (
                endpoint.scheme not in {"http", "https"}
                or not endpoint.hostname
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.query
                or endpoint.fragment
                or (port is not None and port < 1)
            ):
                raise ValueError
        except ValueError:
            raise ValueError("se requiere una URL HTTP(S) sin credenciales ni parámetros") from None
        return value


class RoutingConfig(StrictModel):
    extract: Annotated[list[Text], Field(min_length=1)] = ["internal", "nan"]
    conceptual: Annotated[list[Text], Field(min_length=1)] = ["nan", "internal"]
    plan: Annotated[list[Text], Field(min_length=1)] = ["nan", "internal"]
    weekly: Annotated[list[Text], Field(min_length=1)] = ["nan", "internal"]
    contrast: Annotated[list[Text], Field(min_length=1)] = ["nan", "internal"]


class LLMConfig(StrictModel):
    providers: dict[str, ProviderConfig]
    routing: RoutingConfig = Field(default_factory=RoutingConfig)

    @model_validator(mode="after")
    def known_providers(self) -> Self:
        for route in (
            self.routing.extract,
            self.routing.conceptual,
            self.routing.plan,
            self.routing.weekly,
            self.routing.contrast,
        ):
            if any(name not in self.providers for name in route):
                raise ValueError("el enrutado referencia un proveedor no configurado")
        return self


class EmailConfig(StrictModel):
    smtp_host: Text
    smtp_port: Annotated[int, Field(ge=1, le=65535)] = 587
    username: Text
    password_env: EnvName
    from_address: Text = Field(alias="from")
    to: Text


class DriveConfig(StrictModel):
    remote: Text
    backups_keep_days: PositiveInt = 30


class WebConfig(StrictModel):
    bind: str = "127.0.0.1"
    port: Annotated[int, Field(ge=1, le=65535)] = 8090
    public_base_url: Text
    allowed_tailscale_login: Text

    @field_validator("bind")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        if value != "127.0.0.1":
            raise ValueError("la webapp debe escuchar en 127.0.0.1")
        return value


class KanvasConfig(StrictModel):
    cli: Text = "kanvas"
    write_enabled: bool = False


class Config(StrictModel):
    timezone: str = "Europe/Madrid"
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    paths: PathsConfig
    projects: list[ProjectConfig] = Field(default_factory=list)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    llm: LLMConfig
    email: EmailConfig
    drive: DriveConfig
    web: WebConfig
    kanvas: KanvasConfig = Field(default_factory=KanvasConfig)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("zona horaria desconocida") from None
        return value

    @model_validator(mode="after")
    def unique_projects(self) -> Self:
        ids = [project.id for project in self.projects]
        if len(ids) != len(set(ids)):
            raise ValueError("cada proyecto debe tener un id único")
        return self


def load_config(path: Path) -> Config:
    """Read user configuration; never expand environment variables or credentials."""
    try:
        with path.open(encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ConfigError("No se pudo leer la configuración como YAML seguro.") from None
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        # Error messages and input values may contain secrets, including unknown keys.
        errors = []
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            loc = error["loc"]
            if error["type"] == "extra_forbidden":
                loc = loc[:-1]
            field = ".".join(str(part) for part in loc) or "configuración"
            reason = "campo desconocido" if error["type"] == "extra_forbidden" else error["msg"]
            errors.append(f"{field}: {reason}")
        raise ConfigError("Configuración inválida: " + "; ".join(errors)) from None
