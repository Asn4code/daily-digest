"""SQLite connections and transactional, versioned migrations."""

import sqlite3
from importlib.resources import files
from pathlib import Path


class MigrationError(RuntimeError):
    """The database version cannot be safely migrated."""


def connect(path: Path) -> sqlite3.Connection:
    """Open the application database with WAL and foreign keys enabled."""
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        migrate(connection)
    except BaseException:
        connection.close()
        raise
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    """Apply bundled migrations once, under an exclusive writer transaction."""
    if connection.in_transaction:
        raise MigrationError("Migration requires a connection without an active transaction")
    resources = sorted(
        (
            file
            for file in files(__package__).joinpath("migrations").iterdir()
            if file.name.endswith(".sql")
        ),
        key=lambda file: file.name,
    )
    connection.execute("BEGIN IMMEDIATE")
    try:
        has_meta = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
        ).fetchone()
        row = (
            connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if has_meta
            else None
        )
        if has_meta and row is None:
            raise MigrationError("Database metadata is missing its schema version")
        try:
            current = int(row[0]) if row else 0
        except (ValueError, TypeError):
            raise MigrationError("Invalid database schema version") from None
        if current < 0 or current > len(resources):
            raise MigrationError("Unsupported database schema version")
        for expected, resource in enumerate(resources, 1):
            if int(resource.name.split("_", 1)[0]) != expected:
                raise MigrationError("Non-contiguous migration versions")
            if expected <= current:
                continue
            statement = ""
            for line in resource.read_text(encoding="utf-8").splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    connection.execute(statement)
                    statement = ""
            if statement.strip():
                raise MigrationError("Incomplete migration statement")
            connection.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(expected),),
            )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
