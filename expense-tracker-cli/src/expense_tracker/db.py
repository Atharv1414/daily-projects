"""SQLite connection handling, transactions and versioned schema migrations.

The schema version lives in SQLite's ``PRAGMA user_version``. Each migration runs inside its
own transaction together with the version bump, so a failed migration leaves the database
exactly as it was. Databases created by v1.0 of this tool (version 0, money stored as TEXT)
are upgraded in place without losing data.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .errors import MigrationError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        1,
        "v1.0 schema (amounts stored as TEXT)",
        (
            """CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount TEXT NOT NULL,
                category TEXT NOT NULL,
                spent_on TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '')""",
            """CREATE TABLE IF NOT EXISTS budgets (
                month TEXT NOT NULL,
                category TEXT NOT NULL,
                amount TEXT NOT NULL,
                PRIMARY KEY (month, category))""",
        ),
    ),
    Migration(
        2,
        "integer pence, merchant, source and idempotent import hash",
        (
            """CREATE TABLE expenses_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount_pence INTEGER NOT NULL CHECK (amount_pence > 0),
                category TEXT NOT NULL,
                spent_on TEXT NOT NULL,
                merchant TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual'
                    CHECK (source IN ('manual', 'import', 'recurring')),
                import_hash TEXT UNIQUE,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))""",
            """INSERT INTO expenses_new (id, amount_pence, category, spent_on, note)
               SELECT id, CAST(ROUND(CAST(amount AS REAL) * 100) AS INTEGER),
                      category, spent_on, note
               FROM expenses""",
            "DROP TABLE expenses",
            "ALTER TABLE expenses_new RENAME TO expenses",
            "CREATE INDEX idx_expenses_spent_on ON expenses (spent_on)",
            "CREATE INDEX idx_expenses_category_date ON expenses (category, spent_on)",
            "CREATE INDEX idx_expenses_merchant ON expenses (merchant)",
            """CREATE TABLE budgets_new (
                month TEXT NOT NULL,
                category TEXT NOT NULL,
                amount_pence INTEGER NOT NULL CHECK (amount_pence > 0),
                PRIMARY KEY (month, category))""",
            """INSERT INTO budgets_new (month, category, amount_pence)
               SELECT month, category, CAST(ROUND(CAST(amount AS REAL) * 100) AS INTEGER)
               FROM budgets""",
            "DROP TABLE budgets",
            "ALTER TABLE budgets_new RENAME TO budgets",
        ),
    ),
    Migration(
        3,
        "recurring rules, category rules and import run audit log",
        (
            """CREATE TABLE recurring_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                amount_pence INTEGER NOT NULL CHECK (amount_pence > 0),
                category TEXT NOT NULL,
                merchant TEXT NOT NULL DEFAULT '',
                frequency TEXT NOT NULL CHECK (frequency IN ('weekly', 'monthly', 'yearly')),
                start_date TEXT NOT NULL,
                end_date TEXT)""",
            """CREATE TABLE category_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100)""",
            """CREATE TABLE import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'succeeded', 'failed')),
                rows_read INTEGER NOT NULL DEFAULT 0,
                inserted INTEGER NOT NULL DEFAULT 0,
                duplicates INTEGER NOT NULL DEFAULT 0,
                credits_skipped INTEGER NOT NULL DEFAULT 0,
                rejected INTEGER NOT NULL DEFAULT 0)""",
        ),
    ),
)

SCHEMA_VERSION = MIGRATIONS[-1].version


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection in autocommit mode; multi-statement work uses ``transaction()``."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block atomically. Nested calls join the outer transaction."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection, target: int = SCHEMA_VERSION) -> list[int]:
    """Apply pending migrations up to ``target`` and return the versions applied."""
    current = schema_version(conn)
    if current > SCHEMA_VERSION:
        raise MigrationError(
            f"Database schema v{current} is newer than this tool supports (v{SCHEMA_VERSION})"
        )
    applied = []
    for migration in MIGRATIONS:
        if current < migration.version <= target:
            with transaction(conn):
                for statement in migration.statements:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {migration.version:d}")
            log.info(
                "applied migration",
                extra={"version": migration.version, "description": migration.description},
            )
            applied.append(migration.version)
    return applied


def open_database(path: str | Path) -> sqlite3.Connection:
    conn = connect(path)
    try:
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn
