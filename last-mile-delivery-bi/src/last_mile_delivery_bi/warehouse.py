"""Build the DuckDB warehouse: schema, loads in dependency order, then the SQL views."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .data_generator import GeneratorConfig, generate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

# Dimensions first, then the route-day fact, then the parcel fact that references it.
LOAD_ORDER = [
    "dim_date",
    "dim_depot",
    "dim_route",
    "dim_driver",
    "dim_vehicle",
    "dim_service",
    "fact_route_day",
    "fact_delivery",
]


def _sql_dir(sql_dir: Path | None) -> Path:
    path = sql_dir or SQL_DIR
    if not (path / "schema.sql").exists():
        raise FileNotFoundError(
            f"schema.sql not found in {path}; install the project with `pip install -e .`"
        )
    return path


def create_schema(con: duckdb.DuckDBPyConnection, sql_dir: Path | None = None) -> None:
    """Create every table in schema.sql."""
    con.execute((_sql_dir(sql_dir) / "schema.sql").read_text(encoding="utf-8"))


def create_views(con: duckdb.DuckDBPyConnection, sql_dir: Path | None = None) -> list[str]:
    """Create the reporting views in file-name order and return their names."""
    names = []
    for path in sorted((_sql_dir(sql_dir) / "views").glob("*.sql")):
        con.execute(path.read_text(encoding="utf-8"))
        names.append(path.stem.split("_", 1)[1])
    return names


def load_tables(con: duckdb.DuckDBPyConnection, tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Insert each DataFrame into its table by column name; returns row counts."""
    counts = {}
    for name in LOAD_ORDER:
        df = tables[name]
        con.register("staging_df", df)
        cols = ", ".join(df.columns)
        con.execute(f"INSERT INTO {name} ({cols}) SELECT {cols} FROM staging_df")
        con.unregister("staging_df")
        counts[name] = len(df)
    return counts


def build_warehouse(
    db_path: str | Path = ":memory:",
    config: GeneratorConfig | None = None,
    sql_dir: Path | None = None,
) -> duckdb.DuckDBPyConnection:
    """Generate data and build a complete warehouse. Rebuilds the file if it already exists."""
    if db_path != ":memory:":
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    create_schema(con, sql_dir)
    load_tables(con, generate(config))
    create_views(con, sql_dir)
    return con


def query_df(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pd.DataFrame:
    """Run a query and return a DataFrame with DECIMAL columns converted to float."""
    df = con.execute(sql, params or []).df()
    for col in df.columns:
        if df[col].dtype == object and len(df) and type(df[col].dropna().iloc[0]).__name__ == "Decimal":
            df[col] = df[col].astype(float)
    return df
