"""Human review lifecycle, source corrections and explicit Obsidian fallback."""

import asyncio
import json
import re
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from digest.db import connect
from digest.llm.client import ClientError
from digest.llm.router import Router
from digest.review import records
from digest.review.notes import import_ready, template
from digest.web.app import create_app
from digest.worker import execute
from tests.integration.test_publication import NOW, build
from tests.integration.test_publication import config as config


@pytest.fixture
def report(config):
    ident = build(config)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        document = records.document(db, config, ident)
    return document


def row(config, sql, params=()):
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        return db.execute(sql, params).fetchone()


def submit(config, report, mode="short", text=None):
    values = text or {key: "Mi explicación con otras palabras" for key in records.FIELDS[mode]}
    with records.writing(config) as db:
        ident = records.submit(db, config, report.id, report.results[0].id, mode, values)
    job = row(config, "SELECT id FROM job WHERE kind='contrast' ORDER BY id DESC LIMIT 1")
    return ident, job[0] if job else None


def test_web_submit_hides_automatic_text_and_never_closes_without_decision(config, report):
    app = create_app(config)
    result = report.results[0]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1",
            follow_redirects=True,
        ) as client:
            page = await client.get(f"/review/{result.id}?report_id={report.id}")
            assert page.status_code == 200
            assert "Hay evidencia disponible para contrastar." not in page.text
            token = re.search(r'name="csrf-token" content="([a-f0-9]+)"', page.text)[1]
            data = {
                "submission_id": re.search(r'name="submission_id" value="([a-f0-9]+)"', page.text)[
                    1
                ],
                "csrf_token": token,
                "report_id": report.id,
                "mode": "short",
                **{key: "Mi explicación" for key in records.FIELDS["short"]},
            }
            response = await client.post(f"/review/{result.id}/submit", data=data)
            assert response.status_code == 200 and "Contraste pendiente" in response.text
            review_url = response.url.path
            assert (
                await client.post(f"/review/{result.id}/submit", data=data)
            ).url.path == review_url
            assert row(config, "SELECT count(*) FROM review")[0] == 1
            assert row(config, "SELECT count(*) FROM job WHERE kind='contrast'")[0] == 1
            assert (
                row(config, "SELECT review_state FROM result WHERE id=?", (result.id,))[0]
                == "submitted"
            )
            decision_url = review_url.removesuffix("/result") + "/decide"
            assert (
                await client.post(
                    decision_url, data={"csrf_token": token, "decision": "closed", "doubt": ""}
                )
            ).status_code == 409
            job = row(config, "SELECT id FROM job WHERE kind='contrast'")[0]
            execute(config, job, now=NOW)
            response = await client.get(review_url)
            assert "Contraste con las evidencias" in response.text
            assert (
                row(config, "SELECT review_state FROM result WHERE id=?", (result.id,))[0]
                == "contrasted"
            )
            await client.get("/")
            assert row(config, "SELECT decision FROM review")[0] is None
            decision = {
                "csrf_token": token,
                "decision": "closed",
                "doubt": "Quiero revisar el control",
            }
            assert (await client.post(decision_url, data=decision)).status_code == 200
            assert (await client.post(decision_url, data=decision)).status_code == 200
            assert (
                row(config, "SELECT review_state FROM result WHERE id=?", (result.id,))[0]
                == "closed_by_human"
            )
            assert row(config, "SELECT count(*) FROM job WHERE kind='deliver'")[0] == 1
            assert json.loads(row(config, "SELECT doubts FROM review")[0]) == [decision["doubt"]]

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["short", "full"])
def test_open_review_prevents_replacing_human_text(config, report, mode):
    ident, _ = submit(config, report, mode)
    original = row(config, "SELECT human_text FROM review WHERE id=?", (ident,))[0]
    with pytest.raises(ValueError), records.writing(config) as db:
        records.submit(
            db,
            config,
            report.id,
            report.results[0].id,
            "short",
            {k: "Otro texto" for k in records.FIELDS["short"]},
        )
    assert row(config, "SELECT human_text FROM review WHERE id=?", (ident,))[0] == original


def test_minimal_review_stores_doubt_without_calling_model(config, report):
    ident, job = submit(config, report, "minimal", {"doubt": "No entiendo la comparación"})
    assert job is None
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        record, _ = records.read(db, config, ident)
    assert record["decision"] == "needs_clarification"
    assert record["doubts"] == ["No entiendo la comparación"]
    assert (
        row(config, "SELECT review_state FROM result WHERE id=?", (report.results[0].id,))[0]
        == "needs_clarification"
    )


def test_T25_contrast_can_correct_the_automatic_summary(config, report):
    ident, job = submit(
        config,
        report,
        text={
            "shows": "Mi interpretación respaldada",
            "importance": "Importa contrastar las fuentes",
            "unknown": "El resumen puede ser incorrecto",
        },
    )
    original = Router.generate

    def generate(self, task, **kwargs):
        response = original(self, task, **kwargs)
        if response and kwargs["prompt_name"] == "contrast":
            # Exercise the same production schema/validator with the corrected candidate.
            candidate = response.value.model_dump()
            candidate["summary_errors"] = candidate["supported"][:1]
            response.value.summary_errors = kwargs["validate"](candidate).summary_errors
        return response

    with patch.object(Router, "generate", generate):
        execute(config, job, now=NOW)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        record, _ = records.read(db, config, ident)
    assert record["contrast"]["summary_errors"]
    assert record["decision"] is None
    from tests.e2e.test_web_reading import request

    page = request(create_app(config), path="/reports/" + report.id)
    assert "Resumen automático corregido en la revisión" in page.text
    assert (
        row(config, "SELECT review_state FROM result WHERE id=?", (report.results[0].id,))[0]
        == "contrasted"
    )


def test_failed_contrast_preserves_human_explanation_and_pending_state(config, report):
    ident, job = submit(config, report)
    before = row(config, "SELECT human_text FROM review WHERE id=?", (ident,))[0]
    with patch("digest.llm.client.Client.complete", side_effect=ClientError("transport_error")):
        with pytest.raises(RuntimeError):
            execute(config, job, now=NOW)
    assert row(config, "SELECT human_text,contrast,decision FROM review WHERE id=?", (ident,)) == (
        before,
        None,
        None,
    )
    assert (
        row(config, "SELECT review_state FROM result WHERE id=?", (report.results[0].id,))[0]
        == "submitted"
    )
    with records.writing(config) as db:
        records.retry(db, config, ident)
        records.retry(db, config, ident)
    assert row(config, "SELECT count(*) FROM job WHERE kind='contrast' AND state='queued'")[0] == 1
    retry_job = row(config, "SELECT max(id) FROM job WHERE kind='contrast'")[0]
    execute(config, retry_job, now=NOW)
    assert row(config, "SELECT human_text,decision FROM review WHERE id=?", (ident,)) == (
        before,
        None,
    )


def test_missing_fidelity_audit_never_publishes_a_contrast(config, report):
    ident, job = submit(config, report)
    original = Router.generate

    def generate(self, task, **kwargs):
        return None if kwargs["prompt_name"] == "grounding" else original(self, task, **kwargs)

    with patch.object(Router, "generate", generate), pytest.raises(RuntimeError):
        execute(config, job, now=NOW)
    assert row(config, "SELECT contrast,decision FROM review WHERE id=?", (ident,)) == (None, None)


def test_T21_no_review_keeps_every_result_pending(config, report):
    from tests.e2e.test_web_reading import request

    app = create_app(config)
    assert request(app, path="/reports/" + report.id).status_code == 200
    assert row(config, "SELECT count(*) FROM review")[0] == 0
    assert row(config, "SELECT review_state FROM result")[0] == "pending"


def test_T26_obsidian_pending_is_ignored_and_lista_imports_once(config, report):
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        template(db, config, report)
        note = next(
            (Path(config.paths.obsidian_vault) / config.paths.obsidian_reviews_dir).glob("*.md")
        )
        raw = note.read_text().replace("- Qué muestra:", "- Qué muestra: Hay datos")
        raw = raw.replace("- Por qué importa:", "- Por qué importa: Permite comparar")
        raw = raw.replace("- Qué no sé:", "- Qué no sé: Falta el control")
        note.write_text(raw)
        assert import_ready(db, config) == 0
        assert db.execute("SELECT count(*) FROM review").fetchone()[0] == 0
        note.write_text(raw.replace("estado: pendiente", "estado: lista"))
        human = note.read_bytes()
        assert import_ready(db, config) == 1
        assert import_ready(db, config) == 0
        assert note.read_bytes() == human
        job = db.execute("SELECT id FROM job WHERE kind='contrast'").fetchone()[0]
        ident = db.execute("SELECT id FROM review").fetchone()[0]
    execute(config, job, now=NOW)
    with records.writing(config) as db:
        records.decide(db, config, ident, "needs_clarification", "Qué control necesito")
    delivery = row(config, "SELECT id FROM job WHERE kind='deliver' ORDER BY id DESC LIMIT 1")[0]
    execute(config, delivery, now=NOW)
    assert note.read_bytes() == human
    assert list(note.parent.glob("*-contraste.md"))
    remote = Path(config.drive.remote.removeprefix(":local:")) / "reviews" / ident
    assert (remote / "review.json").is_file()


def test_obsidian_registered_note_cannot_link_to_another_vault_note(config, report):
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        template(db, config, report)
        vault = Path(config.paths.obsidian_vault)
        note = next((vault / config.paths.obsidian_reviews_dir).glob("*.md"))
        other = vault / "personal.md"
        raw = note.read_text().replace("estado: pendiente", "estado: lista")
        raw = raw.replace("- Qué muestra:", "- Qué muestra: Dato personal")
        raw = raw.replace("- Por qué importa:", "- Por qué importa: No importar")
        raw = raw.replace("- Qué no sé:", "- Qué no sé: Privado")
        other.write_text(raw)
        note.unlink()
        note.symlink_to(other)
        assert import_ready(db, config) == 0
        assert db.execute("SELECT count(*) FROM review").fetchone()[0] == 0
        assert other.read_text() == raw


def test_changed_contrast_is_not_served_or_accepted(config, report):
    ident, job = submit(config, report)
    execute(config, job, now=NOW)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        candidate = json.loads(
            db.execute("SELECT contrast FROM review WHERE id=?", (ident,)).fetchone()[0]
        )
        candidate["supported"][0]["text"] = "Otra interpretación sin comprobar"
        db.execute("UPDATE review SET contrast=? WHERE id=?", (json.dumps(candidate), ident))
        with pytest.raises(ValueError, match="binding"):
            records.read(db, config, ident)
    from tests.e2e.test_web_reading import request

    assert request(create_app(config), path=f"/review/{ident}/result").status_code == 404
    with pytest.raises(ValueError), records.writing(config) as db:
        records.decide(db, config, ident, "closed", "")
    assert row(config, "SELECT decision FROM review WHERE id=?", (ident,))[0] is None


def test_minimal_submission_is_idempotent_even_after_its_decision(config, report):
    with records.writing(config) as db:
        first = records.submit(
            db,
            config,
            report.id,
            report.results[0].id,
            "minimal",
            {"doubt": "Mi duda"},
            submission_id="a" * 32,
        )
    with records.writing(config) as db:
        second = records.submit(
            db,
            config,
            report.id,
            report.results[0].id,
            "minimal",
            {"doubt": "Mi duda"},
            submission_id="a" * 32,
        )
    assert first == second
    assert row(config, "SELECT count(*) FROM review")[0] == 1
    assert row(config, "SELECT count(*) FROM job WHERE kind='deliver'")[0] == 1


def test_delayed_duplicate_from_second_form_cannot_reopen_a_decided_review(config, report):
    values = {key: "Mi explicación" for key in records.FIELDS["short"]}
    with records.writing(config) as db:
        first = records.submit(
            db, config, report.id, report.results[0].id, "short", values, submission_id="a" * 32
        )
    with records.writing(config) as db:
        assert (
            records.submit(
                db, config, report.id, report.results[0].id, "short", values, submission_id="b" * 32
            )
            == first
        )
        records.decide(db, config, first, "postponed", "")
    with records.writing(config) as db:
        assert (
            records.submit(
                db, config, report.id, report.results[0].id, "short", values, submission_id="b" * 32
            )
            == first
        )
    assert row(config, "SELECT count(*) FROM review")[0] == 1
    assert row(config, "SELECT count(*) FROM job WHERE kind='contrast'")[0] == 1
    assert (
        row(config, "SELECT review_state FROM result WHERE id=?", (report.results[0].id,))[0]
        == "postponed"
    )


def test_human_text_uses_all_project_privacy_policies_and_redacts_secrets(config, report, tmp_path):
    private = config.projects[0].model_copy(
        update={"id": "private", "root": str(tmp_path / "private"), "external_allowed": False}
    )
    config.projects.append(private)
    values = {key: "Texto con synthetic-password" for key in records.FIELDS["short"]}
    ident, job = submit(config, report, text=values)
    execute(config, job, now=NOW)
    human = row(config, "SELECT human_text FROM review WHERE id=?", (ident,))[0]
    assert "synthetic-password" not in human and "[redactado]" in human
    providers = row(
        config, "SELECT group_concat(DISTINCT provider) FROM llm_call WHERE job_id=?", (job,)
    )[0]
    assert providers == "internal"


def test_missing_project_policy_blocks_human_text_before_any_call(config, report):
    ident, job = submit(config, report)
    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        db.execute(
            "INSERT INTO project(id,name,root,objective,external_allowed,config_hash) "
            "VALUES ('removed','Private','/unavailable','Private',0,'test')"
        )
    with pytest.raises(RuntimeError):
        execute(config, job, now=NOW)
    assert row(config, "SELECT count(*) FROM llm_call WHERE job_id=?", (job,))[0] == 0
    assert row(config, "SELECT contrast,decision FROM review WHERE id=?", (ident,)) == (None, None)


def test_human_wrong_number_can_be_quoted_but_fabricated_quote_is_rejected(config, report):
    ident, _ = submit(
        config,
        report,
        text={
            "shows": "La precisión es de 999999 %",
            "importance": "Revisar",
            "unknown": "No lo sé",
        },
    )
    from digest.llm.schemas import Contrast

    with closing(connect(Path(config.paths.data_dir) / "digest.db")) as db:
        record, _ = records.read(db, config, ident)
    candidate = Contrast(
        supported=[],
        omissions=[],
        unsupported=[{"text": "999999 %", "why": "La evidencia no respalda esa medida"}],
        unverifiable=[],
        summary_errors=[],
    )
    records.check_contrast(candidate, report, record)
    candidate.unsupported[0].text = "Otra frase atribuida a la persona"
    with pytest.raises(ValueError, match="Human quote"):
        records.check_contrast(candidate, report, record)
