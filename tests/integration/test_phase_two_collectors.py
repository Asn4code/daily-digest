"""Read notebooks, coordinates and explicitly scoped messages without execution."""

import json
from datetime import UTC, datetime
from pathlib import Path

from digest.collectors.agent_sessions import AgentSessionsCollector
from digest.collectors.base import CaptureContext
from digest.collectors.notebooks import NotebooksCollector
from digest.collectors.structures import StructuresCollector
from digest.config import ProjectConfig
from tests.integration.test_fixtures import _snapshot


def test_notebook_stored_outputs_are_observed_without_running_code(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    marker = root / "executed"
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {
                "id": "test",
                "cell_type": "code",
                "metadata": {},
                "execution_count": 7,
                "source": f"from pathlib import Path; Path({str(marker)!r}).touch()",
                "outputs": [
                    {"output_type": "stream", "name": "stdout", "text": "old stored output"}
                ],
            }
        ],
    }
    (root / "analysis.ipynb").write_text(json.dumps(notebook))
    project = ProjectConfig(id="test", name="Test", root=str(root), include=["**/*"])
    ctx = CaptureContext(tmp_path / "service", datetime.now(UTC))
    before = _snapshot(root, include_git=True)
    first = NotebooksCollector().collect(project, None, ctx)
    assert first.status == "ok"
    assert len(first.evidence) == 1 and first.evidence[0].event_at is None
    assert first.evidence[0].meta["execution_count"] == 7
    assert first.evidence[0].meta["stored_outputs_only"]
    ctx.previous_payload = first.snapshot_payload
    assert not NotebooksCollector().collect(project, None, ctx).evidence
    notebook["cells"][0]["outputs"][0]["text"] = "changed stored output"
    (root / "analysis.ipynb").write_text(json.dumps(notebook))
    assert len(NotebooksCollector().collect(project, None, ctx).evidence) == 1
    assert not marker.exists()
    (root / "analysis.ipynb").write_text(json.dumps({**notebook, "cells": []}))
    assert len(before) == len(_snapshot(root, include_git=True))


def test_pdb_and_mmcif_metadata_match_without_imports(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "model.pdb").write_text(
        "HEADER    SYNTHETIC\n"
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 20.00           C\n"
        "ATOM      2  CA  GLY B   2       1.000   2.000   3.000  1.00 20.00           C\n"
    )
    (root / "model.cif").write_text(
        "data_test\nloop_\n_atom_site.label_asym_id\n"
        "_atom_site.label_seq_id\n_atom_site.Cartn_x\nA 1 1.0\nB 2 1.0\n#\n"
    )
    project = ProjectConfig(id="test", name="Test", root=str(root))
    before = _snapshot(root, include_git=True)
    output = StructuresCollector().collect(
        project, None, CaptureContext(tmp_path / "service", datetime.now(UTC))
    )
    assert output.status == "ok" and len(output.evidence) == 2
    for e in output.evidence:
        assert e.meta["chains"] == ["A", "B"]
        assert e.meta["residue_count"] == 2 and e.meta["atom_count"] == 2
        assert e.event_at is None
    assert _snapshot(root, include_git=True) == before


def test_codex_sessions_require_exact_project_and_redact_credentials(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    sessions = tmp_path / "sessions"
    sessions.mkdir()

    def rows(cwd):
        return [
            {"type": "session_meta", "payload": {"cwd": str(cwd), "id": "test-session"}},
            {
                "type": "response_item",
                "timestamp": "2026-11-05T10:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                "Verified control. api_key=example-secret "
                                "known-secret-value Bearer some-token"
                            ),
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {"type": "function_call", "arguments": "NEVER_INCLUDE_TOOL"},
            },
        ]

    for name, cwd in [("valid.jsonl", root), ("other.jsonl", tmp_path / "other")]:
        records = rows(cwd)
        records.extend(
            [
                {"type": "turn_context", "payload": {"cwd": str(tmp_path / "other")}},
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "OTHER_PROJECT_EXCLUDED"}],
                    },
                },
            ]
        )
        (sessions / name).write_text("\n".join(json.dumps(r) for r in records))
    project = ProjectConfig(id="test", name="Test", root=str(root), agent_sessions=[str(sessions)])
    ctx = CaptureContext(tmp_path / "service", datetime.now(UTC), secrets=("known-secret-value",))
    output = AgentSessionsCollector().collect(project, None, ctx)
    assert output.status == "ok" and len(output.evidence) == 1
    text = output.evidence[0].excerpt
    assert all(
        s not in text
        for s in [
            "example-secret",
            "known-secret-value",
            "some-token",
            "NEVER_INCLUDE_TOOL",
            "OTHER_PROJECT_EXCLUDED",
        ]
    )
    assert output.evidence[0].event_at is not None
    ctx.previous_payload = output.snapshot_payload
    assert not AgentSessionsCollector().collect(project, None, ctx).evidence


def test_sqlite_agent_readers_are_scoped_redacted_and_do_not_change_databases(
    tmp_path: Path,
) -> None:
    import sqlite3

    root = tmp_path / "project"
    root.mkdir()
    histories = tmp_path / "histories"
    histories.mkdir()
    paths = []
    for agent in ["opencode", "hermes"]:
        path = histories / (agent + ".db")
        paths.append(str(path))
        with sqlite3.connect(path) as db:
            if agent == "opencode":
                db.executescript(
                    "CREATE TABLE session(id TEXT,directory TEXT,time_updated INTEGER);"
                    "CREATE TABLE message(id TEXT,session_id TEXT,data TEXT);"
                    "CREATE TABLE part(id TEXT,message_id TEXT,session_id TEXT,"
                    "time_created INTEGER,data TEXT);"
                )
                for ident, cwd in [("valid", str(root)), ("other", str(tmp_path / "other"))]:
                    db.execute("INSERT INTO session VALUES (?,?,?)", (ident, cwd, 1793872800000))
                    db.execute(
                        "INSERT INTO message VALUES (?,?,?)",
                        (ident, ident, json.dumps({"role": "assistant"})),
                    )
                    db.execute(
                        "INSERT INTO part VALUES (?,?,?,?,?)",
                        (
                            ident,
                            ident,
                            ident,
                            1793872800000,
                            json.dumps(
                                {
                                    "type": "text",
                                    "text": "Control verified. password=hidden known-secret",
                                }
                            ),
                        ),
                    )
            else:
                db.executescript(
                    "CREATE TABLE sessions(id TEXT,cwd TEXT);"
                    "CREATE TABLE messages(id INTEGER,session_id TEXT,timestamp REAL,"
                    "role TEXT,content TEXT);"
                )
                for number, (ident, cwd) in enumerate(
                    [("valid", str(root)), ("other", str(tmp_path / "other"))]
                ):
                    db.execute("INSERT INTO sessions VALUES (?,?)", (ident, cwd))
                    db.execute(
                        "INSERT INTO messages VALUES (?,?,?,?,?)",
                        (
                            number,
                            ident,
                            1793872800,
                            "assistant",
                            "Control verified. password=hidden known-secret",
                        ),
                    )
    project = ProjectConfig(id="test", name="Test", root=str(root), agent_sessions=paths)
    ctx = CaptureContext(tmp_path / "service", datetime.now(UTC), secrets=("known-secret",))
    before = _snapshot(histories, include_git=True)
    output = AgentSessionsCollector().collect(project, None, ctx)
    assert output.status == "ok" and len(output.evidence) == 2
    assert {e.meta["agent"] for e in output.evidence} == {"opencode", "hermes"}
    assert all(e.event_at is not None for e in output.evidence)
    assert all(
        "hidden" not in e.excerpt and "known-secret" not in e.excerpt for e in output.evidence
    )
    assert all("other" not in e.locator for e in output.evidence)
    assert _snapshot(histories, include_git=True) == before
    ctx.previous_payload = output.snapshot_payload
    assert not AgentSessionsCollector().collect(project, None, ctx).evidence


def test_sqlite_wal_is_reported_without_touching_live_sidecars(tmp_path: Path) -> None:
    import sqlite3
    from contextlib import closing

    path = tmp_path / "hermes.db"
    project = ProjectConfig(
        id="test", name="Test", root=str(tmp_path / "project"), agent_sessions=[str(path)]
    )
    Path(project.root).mkdir()
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.executescript(
            "CREATE TABLE sessions(id TEXT,cwd TEXT);"
            "CREATE TABLE messages(id INTEGER,session_id TEXT,timestamp REAL,"
            "role TEXT,content TEXT);"
        )
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO sessions VALUES (?,?)", ("new", project.root))
        writer.commit()
        before = _snapshot(tmp_path, include_git=True)
        output = AgentSessionsCollector().collect(
            project, None, CaptureContext(tmp_path / "service", datetime.now(UTC))
        )
        assert output.status == "partial"
        assert any(x.reason == "sqlite_wal_not_read" for x in output.omitted)
        assert _snapshot(tmp_path, include_git=True) == before
