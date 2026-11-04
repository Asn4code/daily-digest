"""Exercise schema constraints and migration transaction boundaries."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from digest.db import MigrationError, connect, migrate


def test_migration_is_idempotent_and_preserves_data(tmp_path: Path) -> None:
    path = tmp_path / "digest.db"
    with closing(connect(path)) as db:
        assert db.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        db.execute("INSERT INTO project(id,name,root,config_hash) VALUES ('p','P','/project','h')")
        migrate(db)
    with closing(connect(path)) as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == ("1",)
        assert db.execute("SELECT name FROM project").fetchall() == [("P",)]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO project(id,name,root,config_hash) VALUES ('p','P','/project','h')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO result(id,project_id,title,first_seen_at) VALUES ('r','bad','R','t')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO result(id,project_id,title,first_seen_at,review_state) "
                "VALUES ('r','p','R','t','understood')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO job(kind,requested_by,state,created_at) "
                "VALUES ('daily','cli','invalid','t')"
            )


def test_evidence_unique_and_time_quality(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "digest.db")) as db:
        db.execute("INSERT INTO project(id,name,root,config_hash) VALUES ('p','P','/project','h')")
        insert = (
            "INSERT INTO evidence(id,project_id,source,kind,locator,observed_at,"
            "time_quality,content_hash,excerpt) VALUES (?, 'p','git','commit','sha','t',?,'h','x')"
        )
        db.execute(insert, ("ev1", "event"))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(insert, ("ev2", "observed"))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(insert, ("ev3", "unknown"))


def test_partial_migration_rolls_back(tmp_path: Path) -> None:
    with closing(sqlite3.connect(tmp_path / "db", isolation_level=None)) as db:
        db.execute("CREATE TABLE evidence (original TEXT)")
        with pytest.raises(sqlite3.OperationalError):
            migrate(db)
        assert not db.in_transaction
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("evidence",)
        ]


def test_future_schema_rejected_without_changes(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "db")) as db:
        db.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
        with pytest.raises(MigrationError):
            migrate(db)
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == (
            "999",
        )
