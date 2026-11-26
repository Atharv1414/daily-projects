"""trust-bi: generate data, build the warehouse, query metrics, render charts and dashboard."""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from .disclosure import suppress
from .generate import generate
from .semantic import TABLES, MetricQuery, Principal, SemanticLayer
from .warehouse import build

RAW = Path("data/raw")
DB = Path("data/warehouse.duckdb")


def _layer(args) -> SemanticLayer:
    raw = Path(args.raw)
    if not (raw / "marks.parquet").exists():
        print("generating raw data:", generate(raw, scale=args.scale))
    db = Path(args.db)
    if db.exists():
        db.unlink()
    con, report = build(raw, db)
    print(
        f"built warehouse {db} in {sum(report.seconds.values()):.2f} s: "
        + ", ".join(f"{k}={v:,}" for k, v in report.rows.items())
    )
    failed = [c["check_name"] for c in report.checks if not c["passed"]]
    print(f"{len(report.checks)} data-quality checks, {len(failed)} failed {failed or ''}")
    return SemanticLayer(con)


def _filters(items: list[str]) -> dict:
    out: dict = {}
    for item in items:
        key, _, value = item.partition("=")
        out[key] = {"true": True, "false": False}.get(value.lower(), value)
    return out


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.WARNING)
    p = argparse.ArgumentParser(prog="trust-bi")
    p.add_argument("--raw", default=str(RAW))
    p.add_argument("--db", default=str(DB))
    p.add_argument("--scale", type=float, default=1.0)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    q = sub.add_parser("query")
    q.add_argument("--metrics", required=True)
    q.add_argument("--by", default="")
    q.add_argument("--filter", action="append", default=[])
    q.add_argument("--role", default="trust")
    q.add_argument("--suppress", action="store_true")
    sub.add_parser("charts")
    sub.add_parser("dashboard")
    sub.add_parser("bench")
    sub.add_parser("all")
    args = p.parse_args(argv)

    sl = _layer(args)
    if args.command == "query":
        by = [b for b in args.by.split(",") if b]
        df, plan = sl.query(
            MetricQuery(args.metrics.split(","), by, _filters(args.filter)),
            Principal.parse(args.role),
        )
        if args.suppress:
            df = suppress(df, by).drop(columns="suppressed")
        print(
            f"table: {plan.table} ({plan.rows_in_table:,} rows) - {plan.reason}; "
            f"{plan.seconds * 1000:.1f} ms"
        )
        print(df.to_string(index=False))
    if args.command in {"charts", "all"}:
        from .charts import render

        for path in render(sl, Path("docs")):
            print("chart:", path)
    if args.command in {"dashboard", "all"}:
        from .dashboard import build as build_dashboard

        pages = build_dashboard(sl, Path("reports/dashboard"))
        print(f"dashboard: {len(pages)} pages in reports/dashboard/")
    if args.command in {"bench", "all"}:
        bench(sl)


def bench(sl: SemanticLayer, repeats: int = 20) -> None:
    """Same question, every table that can answer it: shows what the navigator saves."""
    query = MetricQuery(["attendance_rate", "unauthorised_absence_rate"], ["school", "term"])
    chosen = sl.choose(query)[0].name
    print(f"\nbenchmark: {query.metrics} by {query.by} (navigator picks {chosen})")
    for table in TABLES:
        if not set(query.by) <= table.dims:
            continue
        times = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            sl.query(query, table_name=table.name)
            times.append(time.perf_counter() - t0)
        times.sort()
        print(
            f"  {table.name:<26} {sl._sizes[table.name]:>10,} rows  "
            f"median {times[len(times) // 2] * 1000:7.2f} ms"
        )


if __name__ == "__main__":
    main()
