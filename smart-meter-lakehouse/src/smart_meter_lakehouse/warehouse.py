"""DuckDB connection management and schema migrations."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from smart_meter_lakehouse.schema import MIGRATIONS

log = logging.getLogger(__name__)


def connect(path: Path | str) -> duckdb.DuckDBPyConnection:
    """Open the warehouse and apply any pending migrations (idempotent)."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    migrate(con)
    return con


def current_version(con: duckdb.DuckDBPyConnection) -> int:
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, "
        "description VARCHAR, applied_at TIMESTAMP DEFAULT current_timestamp)"
    )
    (version,) = con.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(version)


def migrate(con: duckdb.DuckDBPyConnection) -> list[int]:
    applied = []
    version = current_version(con)
    for number, description, ddl in MIGRATIONS:
        if number <= version:
            continue
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(ddl)
            con.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                [number, description],
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        log.info("applied migration %s: %s", number, description)
        applied.append(number)
    return applied


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    row = con.execute(sql, params or []).fetchone()
    return row[0] if row else None
