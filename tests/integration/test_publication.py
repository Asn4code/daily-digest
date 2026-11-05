"""Real local SMTP and local immutable remote; no real accounts or providers."""

import json
import smtplib
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from unittest.mock import patch

import pytest
from weasyprint.urls import FatalURLFetchingError

from digest.config import Config, load_config
from digest.db import connect
from digest.publish.deliveries import deliver_report
from digest.report.pdf import RasterFetcher
from digest.worker import enqueue, execute
from tests.fixtures.doubles import LocalSMTP
from tests.fixtures.make_projects import _kanvas, build_projects

NOW = datetime(2026, 11, 4, 19, tzinfo=UTC)


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    path = build_projects(tmp_path / "projects")
    config = load_config(path)
    config.projects = config.projects[:1]
    config.email.password_env = "DIGEST_TEST_SMTP_PASSWORD"
    monkeypatch.setenv("DIGEST_TEST_SMTP_PASSWORD", "synthetic-password")
    try:
        yield config
    finally:
        (path.parent / "proj-fail/no-access").chmod(0o700)


def build(config: Config, *, since: datetime | None = None, until: datetime | None = None) -> str:
    job = enqueue(
        config,
        "daily",
        params={
            "no_send": True,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
    )
    path = Path(execute(config, job, now=NOW))
    return json.loads(path.with_suffix(".json").read_text())["id"]


def test_T02_all_40_tasks_reach_email_and_local_copies(config: Config) -> None:
    root = Path(config.projects[0].root)
    kanvas = _kanvas()
    kanvas.now_iso = lambda: NOW.isoformat()

    def add_tasks(board):
        for number in range(2, 41):
            kanvas.add_task(
                board, f"Resultado {number}", board["groups"][0], state="done", by="fixture-agent"
            )

    kanvas.mutate(str(root / "kanvas.json"), add_tasks)
    ident = build(config)
    with LocalSMTP() as server, patch("smtplib.SMTP.starttls"), patch("smtplib.SMTP.login"):
        config.email.smtp_port = server.port
        with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
            outcomes = deliver_report(db, config, ident)
            assert outcomes == {"obsidian": "sent", "drive": "sent", "email": "sent"}
            attempts = db.execute(
                "SELECT channel,attempts FROM delivery ORDER BY channel"
            ).fetchall()
            assert deliver_report(db, config, ident) == outcomes
            assert (
                db.execute("SELECT channel,attempts FROM delivery ORDER BY channel").fetchall()
                == attempts
            )
        assert len(server.messages) == 1
        message = BytesParser(policy=default).parsebytes(server.messages[0])
        plain = message.get_body(preferencelist=("plain",)).get_content()
        for number in range(1, 41):
            assert plain.count(f"AN-{number:02d} —") == 1
        assert message["Message-ID"] == f"<{ident}@daily-digest.local>"
        assert message.get_body(preferencelist=("html",)) is not None
        assert len([part for part in message.walk() if part.get_content_type() == "image/png"]) in {
            1,
            2,
        }
    vault = Path(config.paths.obsidian_vault) / config.paths.obsidian_digest_dir
    assert list(vault.glob("*.md"))
    remote = Path(config.drive.remote.removeprefix(":local:")) / "reports/daily" / ident
    assert (remote / "report.md").is_file()
    assert (remote / "report.pdf").read_bytes().startswith(b"%PDF-")
    assert list(remote.glob("figures/*.png"))


def test_T23_data_disconnect_is_uncertain_and_never_replayed(config: Config) -> None:
    ident = build(config)
    with (
        LocalSMTP(disconnect_after_data=True) as server,
        patch("smtplib.SMTP.starttls"),
        patch("smtplib.SMTP.login"),
    ):
        config.email.smtp_port = server.port
        with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
            outcome = deliver_report(db, config, ident)
            assert outcome["email"] == "uncertain"
            assert len(server.messages) == 1
            assert deliver_report(db, config, ident)["email"] == "uncertain"
            assert len(server.messages) == 1
            assert db.execute("SELECT attempts FROM delivery WHERE channel='email'").fetchone() == (
                1,
            )


def test_T22_email_failure_does_not_repeat_successful_channels(config: Config) -> None:
    ident = build(config)
    with LocalSMTP() as server, patch("smtplib.SMTP.starttls"):
        config.email.smtp_port = server.port
        with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
            with patch(
                "smtplib.SMTP.login", side_effect=smtplib.SMTPAuthenticationError(535, b"rejected")
            ):
                outcomes = deliver_report(db, config, ident)
            assert outcomes["drive"] == "sent" and outcomes["email"] == "failed"
            with patch("smtplib.SMTP.login"):
                assert deliver_report(db, config, ident)["email"] == "sent"
            assert db.execute("SELECT attempts FROM delivery WHERE channel='drive'").fetchone() == (
                1,
            )
            assert db.execute("SELECT attempts FROM delivery WHERE channel='email'").fetchone() == (
                2,
            )
            assert len(server.messages) == 1


def test_T24_revision_keeps_human_text_and_remote_original(config: Config) -> None:
    start = NOW.replace(hour=0)
    end = NOW
    first = build(config, since=start, until=end)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert deliver_report(db, config, first, channel="obsidian")["obsidian"] == "sent"
        assert deliver_report(db, config, first, channel="drive")["drive"] == "sent"
        root = Path(config.paths.obsidian_vault) / config.paths.obsidian_reviews_dir
        root.mkdir()
        human = root / "human.md"
        human.write_text("Mi interpretación personal")
        original = (
            Path(config.paths.obsidian_vault) / config.paths.obsidian_digest_dir / "2026-11-04.md"
        )
        original.write_text("Anotación humana que no se pisa")
        db.execute("UPDATE delivery SET state='failed' WHERE channel='obsidian'")
        assert deliver_report(db, config, first, channel="obsidian")["obsidian"] == "failed"
    second = build(config, since=start, until=end)
    assert second.endswith("_r2")
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert deliver_report(db, config, second, channel="obsidian")["obsidian"] == "sent"
        assert deliver_report(db, config, second, channel="drive")["drive"] == "sent"
    assert original.read_text() == "Anotación humana que no se pisa"
    assert human.read_text() == "Mi interpretación personal"
    assert original.with_name("2026-11-04-r2.md").is_file()


def test_pdf_fetcher_rejects_network_and_external_files(tmp_path: Path) -> None:
    fetch = RasterFetcher(tmp_path)
    for url in ["https://example.invalid/a.png", "file:///etc/passwd", "file://outside/a.png"]:
        with pytest.raises(FatalURLFetchingError):
            fetch.fetch(url)


def test_obsidian_symlink_cannot_write_to_project(config: Config) -> None:
    ident = build(config)
    vault = Path(config.paths.obsidian_vault)
    (vault / config.paths.obsidian_digest_dir).symlink_to(
        config.projects[0].root, target_is_directory=True
    )
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert deliver_report(db, config, ident, channel="obsidian")["obsidian"] == "failed"
    assert not (Path(config.projects[0].root) / "2026-11-04.md").exists()


def test_malicious_title_is_escaped_in_email_and_obsidian(config: Config) -> None:
    root = Path(config.projects[0].root)
    kanvas = _kanvas()
    title = "<script>alert(1)</script> [abrir](javascript:alert(2))"

    def change_title(board):
        board["tasks"][0]["title"] = title

    kanvas.mutate(str(root / "kanvas.json"), change_title)
    ident = build(config)
    with LocalSMTP() as server, patch("smtplib.SMTP.starttls"), patch("smtplib.SMTP.login"):
        config.email.smtp_port = server.port
        with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
            assert deliver_report(db, config, ident)["email"] == "sent"
        message = BytesParser(policy=default).parsebytes(server.messages[0])
        html = message.get_body(preferencelist=("html",)).get_content()
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert 'href="javascript:' not in html
    note = next((Path(config.paths.obsidian_vault) / config.paths.obsidian_digest_dir).glob("*.md"))
    from markdown_it import MarkdownIt

    rendered = MarkdownIt("commonmark", {"html": True}).render(note.read_text())
    assert "<script>" not in rendered
    assert 'href="javascript:' not in rendered


def test_changed_report_cannot_overwrite_immutable_remote(config: Config) -> None:
    ident = build(config)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        assert deliver_report(db, config, ident, channel="drive")["drive"] == "sent"
        json_path = Path(
            db.execute("SELECT json_path FROM report WHERE id=?", (ident,)).fetchone()[0]
        )
        remote = (
            Path(config.drive.remote.removeprefix(":local:"))
            / "reports/daily"
            / ident
            / "report.md"
        )
        original = remote.read_bytes()
        json_path.with_suffix(".md").write_text("Changed generated report with a different size")
        db.execute("UPDATE delivery SET state='failed' WHERE channel='drive'")
        assert deliver_report(db, config, ident, channel="drive")["drive"] == "failed"
        assert remote.read_bytes() == original
