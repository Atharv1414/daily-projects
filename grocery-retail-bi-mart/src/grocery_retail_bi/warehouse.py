"""Warehouse build: land raw extracts, run the SQL models, load facts incrementally."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from grocery_retail_bi.models import FACT_DDL, FACT_INSERT, ordered

log = logging.getLogger("grocery_retail_bi.warehouse")

EPOCH = datetime(1900, 1, 1)
FAR_FUTURE = datetime(9999, 12, 31)


class WarehouseError(RuntimeError):
    pass


@dataclass(frozen=True)
class BatchResult:
    batch_id: int
    watermark_from: datetime
    watermark_to: datetime | None
    rows_inserted: int
    late_rows: int
    seconds: float


def run(conn: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list:
    """Execute and fully consume the result (DuckDB 2 refuses new work on a connection with an
    unfinished result, so DDL/DML results are drained here)."""
    return conn.execute(sql, params).fetchall() if params else conn.execute(sql).fetchall()


def connect(path: Path | str = ":memory:") -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path))


def land_raw(conn: duckdb.DuckDBPyConnection, raw_dir: Path) -> dict[str, int]:
    """Load source extracts into the ``raw`` schema with explicit types (no type guessing)."""
    files = {
        "stores_snapshot": raw_dir / "stores_snapshot.csv",
        "products_snapshot": raw_dir / "products_snapshot.csv",
        "store_targets": raw_dir / "store_targets.csv",
        "sales_lines": raw_dir / "sales_lines.csv",
        "promotions": raw_dir / "promotions.json",
    }
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        raise WarehouseError(f"missing source files: {missing}. Run `bi-mart generate` first.")
    run(
        conn,
        "CREATE SCHEMA IF NOT EXISTS raw; CREATE SCHEMA IF NOT EXISTS stg; "
        "CREATE SCHEMA IF NOT EXISTS mart;",
    )
    sales_types = {
        "line_id": "VARCHAR",
        "basket_id": "VARCHAR",
        "store_code": "VARCHAR",
        "sale_ts": "TIMESTAMP",
        "product_code": "VARCHAR",
        "quantity": "INTEGER",
        "unit_price": "DOUBLE",
        "discount_amount": "DOUBLE",
        "net_amount": "DOUBLE",
        "promo_code": "VARCHAR",
        "loyalty_id": "BIGINT",
        "loaded_at": "TIMESTAMP",
    }
    run(
        conn,
        "CREATE OR REPLACE TABLE raw.sales_lines AS SELECT * FROM read_csv(?, header=true, "
        "columns=?)",
        [str(files["sales_lines"]), sales_types],
    )
    for name in ("stores_snapshot", "products_snapshot", "store_targets"):
        run(
            conn,
            f"CREATE OR REPLACE TABLE raw.{name} AS SELECT * FROM read_csv(?, header=true)",
            [str(files[name])],
        )
    run(
        conn,
        "CREATE OR REPLACE TABLE raw.promotions AS SELECT * FROM read_json(?, format='array')",
        [str(files["promotions"])],
    )
    return {n: conn.execute(f"SELECT COUNT(*) FROM raw.{n}").fetchall()[0][0] for n in files}


def build_models(conn: duckdb.DuckDBPyConnection) -> list[str]:
    run(conn, FACT_DDL)
    built = []
    for model in ordered():
        kind = "VIEW" if model.kind == "view" else "TABLE"
        run(conn, f"CREATE OR REPLACE {kind} {model.name} AS {model.sql}")
        built.append(model.name)
    return built


def watermark(conn: duckdb.DuckDBPyConnection) -> datetime:
    value = conn.execute("SELECT max(loaded_at) FROM mart.fact_sales_line").fetchall()[0][0]
    return value or EPOCH


def load_facts(conn: duckdb.DuckDBPyConnection, upto: datetime | None = None) -> BatchResult:
    """Load every staged line with loaded_at in (watermark, upto]. Idempotent: re-running with
    the same ``upto`` inserts nothing, because of both the watermark and the line_id anti-join."""
    t0 = time.perf_counter()
    start = watermark(conn)
    end = upto or FAR_FUTURE
    batch_id = conn.execute(
        "SELECT COALESCE(max(batch_id), 0) + 1 FROM mart.load_batches"
    ).fetchall()[0][0]
    before = conn.execute("SELECT COUNT(*) FROM mart.fact_sales_line").fetchall()[0][0]
    run(conn, "BEGIN TRANSACTION")
    try:
        run(conn, FACT_INSERT, [batch_id, start, end])
        inserted = (
            conn.execute("SELECT COUNT(*) FROM mart.fact_sales_line").fetchall()[0][0] - before
        )
        late = conn.execute(
            """SELECT COUNT(*) FROM mart.fact_sales_line f JOIN mart.dim_date d USING (date_key)
               WHERE f.batch_id = ? AND f.loaded_at - d.date > INTERVAL 2 DAY""",
            [batch_id],
        ).fetchall()[0][0]
        run(
            conn,
            "INSERT INTO mart.load_batches VALUES (?, now(), ?, ?, ?, ?)",
            [batch_id, start, upto, inserted, late],
        )
        run(conn, "COMMIT")
    except Exception:
        run(conn, "ROLLBACK")
        raise
    result = BatchResult(batch_id, start, upto, inserted, late, time.perf_counter() - t0)
    log.info("fact batch", extra={"batch": result.__dict__})
    return result


def build(
    raw_dir: Path,
    db_path: Path | str = ":memory:",
    incremental_cutoffs: list[datetime] | None = None,
) -> tuple[duckdb.DuckDBPyConnection, dict]:
    """Full build. With ``incremental_cutoffs`` the fact is loaded in several batches, as a
    nightly schedule would, which exercises the watermark and late-arriving logic."""
    t0 = time.perf_counter()
    if db_path != ":memory:" and Path(db_path).exists():
        Path(db_path).unlink()
    conn = connect(db_path)
    raw_counts = land_raw(conn, raw_dir)
    t_raw = time.perf_counter()
    models = build_models(conn)
    t_models = time.perf_counter()
    batches = [load_facts(conn, c) for c in (incremental_cutoffs or [])]
    batches.append(load_facts(conn))
    t_end = time.perf_counter()
    stats = {
        "raw_rows": raw_counts,
        "models": models,
        "batches": [b.__dict__ for b in batches],
        "fact_rows": conn.execute("SELECT COUNT(*) FROM mart.fact_sales_line").fetchall()[0][0],
        "timings_s": {
            "land_raw": round(t_raw - t0, 3),
            "models": round(t_models - t_raw, 3),
            "facts": round(t_end - t_models, 3),
            "total": round(t_end - t0, 3),
        },
    }
    return conn, stats
