"""Builds the DuckDB mart from source frames."""

from __future__ import annotations

import logging
import time
from importlib import resources
from pathlib import Path

import duckdb
import pandas as pd

log = logging.getLogger(__name__)


def sql_files() -> list[tuple[str, str]]:
    folder = resources.files("law_firm_profitability_bi") / "sql"
    files = [f for f in folder.iterdir() if f.name.endswith(".sql")]
    return [(f.name, f.read_text()) for f in sorted(files, key=lambda f: f.name)]


def build(con: duckdb.DuckDBPyConnection, sources: dict[str, pd.DataFrame]) -> dict[str, float]:
    """Loads the raw schema and runs every model in order. All or nothing."""
    timings: dict[str, float] = {}
    con.begin()
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        for name, frame in sources.items():
            con.register("incoming", frame)
            con.execute(f"CREATE OR REPLACE TABLE raw.{name} AS SELECT * FROM incoming")
            con.unregister("incoming")
        for name, sql in sql_files():
            started = time.perf_counter()
            con.execute(sql)
            timings[name] = time.perf_counter() - started
            log.info("built %s in %.2fs", name, timings[name])
        con.commit()
    except Exception:
        con.rollback()
        raise
    return timings


def open_database(path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if read_only and not path.exists():
        raise FileNotFoundError(f"{path} does not exist; run `law-bi build` first")
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)
