"""Validate configuration contracts without accessing real projects or services."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from digest.config import Config, ConfigError, load_config

EXAMPLE = Path(__file__).resolve().parents[2] / "config.example.yaml"


def test_example_and_project_addition(tmp_path: Path) -> None:
    config = load_config(EXAMPLE)
    assert config.timezone == "Europe/Madrid"
    assert config.email.from_address == "USER@gmail.com"
    data = config.model_dump(by_alias=True)
    second = deepcopy(data["projects"][0])
    second.update(id="second", root=str(tmp_path / "second"))
    data["projects"].append(second)
    assert len(Config.model_validate(data).projects) == 2
    data["projects"] = []
    assert Config.model_validate(data).projects == []


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("limits", "max_file_bytes", 0),
        ("limits", "capture_timeout_seconds", "300"),
        ("web", "port", 65536),
        ("web", "bind", "0.0.0.0"),
        ("schedule", "daily", "25:00"),
        ("schedule", "weekly", "10:00"),
        ("paths", "obsidian_digest_dir", "../other"),
        ("paths", "data_dir", "relative"),
        ("kanvas", "write_enabled", "false"),
        ("email", "password", "SENSITIVE_TEST_VALUE"),
    ],
)
def test_invalid_values_are_rejected(
    section: str, field: str, value: object, tmp_path: Path
) -> None:
    data = load_config(EXAMPLE).model_dump(by_alias=True)
    data[section][field] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert section in str(error.value)
    assert "SENSITIVE_TEST_VALUE" not in str(error.value)


@pytest.mark.parametrize("case", ["duplicate", "routing", "unknown", "timezone"])
def test_invalid_relationships(case: str, tmp_path: Path) -> None:
    data = load_config(EXAMPLE).model_dump(by_alias=True)
    if case == "duplicate":
        data["projects"].append(deepcopy(data["projects"][0]))
    elif case == "routing":
        data["llm"]["routing"]["extract"] = ["missing"]
    elif case == "unknown":
        data["projects"][0]["unexpected"] = True
    else:
        data["timezone"] = "Invalid/Zone"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize("content", ["[", "!!python/object:example {}", "null", "[]"])
def test_yaml_failure_is_redacted(content: str, tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_environment_credentials_are_not_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "SENSITIVE_TEST_VALUE")
    config = load_config(EXAMPLE)
    assert "SENSITIVE_TEST_VALUE" not in repr(config)
    assert config.llm.providers["internal"].api_key_env == "QWEN_API_KEY"


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "https://user:private@host/v1",
        "https://host:bad/v1",
        "https://host/v1?key=private",
    ],
)
def test_provider_endpoint_rejects_secrets_and_invalid_urls(url: str, tmp_path: Path) -> None:
    data = load_config(EXAMPLE).model_dump(by_alias=True)
    data["llm"]["providers"]["internal"]["base_url"] = url
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert "base_url" in str(error.value)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("through_cli", [False, True])
def test_dynamic_provider_keys_are_redacted(tmp_path: Path, through_cli: bool) -> None:
    from typer.testing import CliRunner

    from digest.cli import app

    data = load_config(EXAMPLE).model_dump(by_alias=True)
    secret = "FAKE_SECRET_MAPPING_KEY"
    data["llm"]["providers"][secret] = {"timeout_s": "bad"}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    if through_cli:
        result = CliRunner().invoke(app, ["--config", str(path), "doctor", "--offline"])
        assert result.exit_code == 2
        output = result.output
    else:
        with pytest.raises(ConfigError) as error:
            load_config(path)
        output = str(error.value)
    assert secret not in output
    assert "llm.providers.<proveedor>" in output
    assert "timeout_s" in output
