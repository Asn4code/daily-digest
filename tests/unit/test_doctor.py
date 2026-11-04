"""Doctor uses synthetic requests, never sends mail, and redacts failures."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from digest.cli import app
from digest.config import Config, load_config
from digest.doctor import _credential, _provider, _smtp, diagnose


@pytest.fixture
def config(tmp_path: Path) -> Config:
    example = Path(__file__).resolve().parents[2] / "config.example.yaml"
    data = load_config(example).model_dump(by_alias=True)
    root = tmp_path / "project"
    root.mkdir()
    (root / "kanvas.json").write_text('{"kanvas":1,"tasks":[],"groups":[]}')
    data["projects"][0]["root"] = str(root)
    data["paths"].update(data_dir=str(tmp_path), obsidian_vault=str(tmp_path))
    data["llm"]["providers"]["internal"]["base_url"] = "https://provider.invalid/v1"
    return Config.model_validate(data)


def test_offline_reads_only(config: Config) -> None:
    root = Path(config.projects[0].root)
    before = (root / "kanvas.json").read_bytes()
    with (
        patch("digest.doctor.run", side_effect=AssertionError("no process")),
        patch("digest.doctor._provider", side_effect=AssertionError("no network")),
    ):
        checks = diagnose(config, offline=True)
    assert all(check.status != "error" for check in checks)
    assert checks[-1].status == "omitido"
    assert (root / "kanvas.json").read_bytes() == before
    assert list(root.iterdir()) == [root / "kanvas.json"]


def test_bad_board_reported(config: Config) -> None:
    (Path(config.projects[0].root) / "kanvas.json").write_text('{"kanvas":2}')
    assert any(check.status == "error" for check in diagnose(config, offline=True))


def test_synthetic_json_probe(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = config.llm.providers["internal"]
    monkeypatch.setenv(provider.api_key_env, "PRIVATE_TEST_CREDENTIAL")
    connection = MagicMock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read.return_value = json.dumps(
        {"choices": [{"message": {"content": '{"ok":true}'}}]}
    ).encode()
    with patch("digest.doctor.http.client.HTTPSConnection", return_value=connection):
        assert _provider(provider) == ""
    payload = json.loads(connection.request.call_args.kwargs["body"])
    assert payload["messages"] == [
        {"role": "user", "content": 'Devuelve solo el JSON {"ok": true}.'}
    ]
    assert "PRIVATE_TEST_CREDENTIAL" not in json.dumps(payload)
    connection.close.assert_called_once()


def test_provider_errors_do_not_leak_credentials(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "PRIVATE_TEST_CREDENTIAL")
    connection = MagicMock()
    connection.request.side_effect = OSError("PRIVATE_TEST_CREDENTIAL")
    with patch("digest.doctor.http.client.HTTPSConnection", return_value=connection):
        assert _provider(config.llm.providers["internal"]) == "falló la comprobación sintética"


def test_smtp_authenticates_without_sending(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMTP_PASSWORD", "PRIVATE_TEST_CREDENTIAL")
    smtp = MagicMock()
    smtp.noop.return_value = (250, b"ok")
    with patch("digest.doctor.smtplib.SMTP") as factory:
        factory.return_value.__enter__.return_value = smtp
        assert _smtp(config) == ""
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with(config.email.username, "PRIVATE_TEST_CREDENTIAL")
    smtp.sendmail.assert_not_called()
    smtp.send_message.assert_not_called()


def test_credentials_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCTOR_TEST_KEY", raising=False)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    (tmp_path / "secrets.env").write_text('DOCTOR_TEST_KEY="private"\n')
    assert _credential("DOCTOR_TEST_KEY") == "private"
    monkeypatch.setenv("DOCTOR_TEST_KEY", "environment")
    assert _credential("DOCTOR_TEST_KEY") == "environment"


def test_cli_offline(config: Config, tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(by_alias=True)))
    result = CliRunner().invoke(app, ["--config", str(path), "doctor", "--offline"])
    assert result.exit_code == 0
    assert "sin procesos ni peticiones de red" in result.output
    path.write_text("password: PRIVATE_TEST_CREDENTIAL")
    result = CliRunner().invoke(app, ["--config", str(path), "doctor", "--offline"])
    assert result.exit_code == 2
    assert "PRIVATE_TEST_CREDENTIAL" not in result.output
