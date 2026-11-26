"""Command-line interface: ``delivery-bi <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

from .charts import build_charts
from .dashboard import build_dashboard, latest_period
from .data_generator import GeneratorConfig
from .metrics import KPIS, compute_kpis, format_value, kpi_definitions_markdown, rag_status
from .quality import run_checks
from .warehouse import build_warehouse, query_df

DEFAULT_DB = Path("warehouse/delivery.duckdb")


def _connect(db: Path) -> duckdb.DuckDBPyConnection:
    if not db.exists():
        print(f"{db} not found, building it first.")
        return build_warehouse(db)
    return duckdb.connect(str(db))


def cmd_build(args: argparse.Namespace) -> int:
    con = build_warehouse(args.db, GeneratorConfig(seed=args.seed))
    for table in ["fact_delivery", "fact_route_day", "dim_route", "dim_driver", "dim_vehicle"]:
        print(f"{table:<16} {con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:>9,} rows")
    print(f"Warehouse written to {args.db}")
    return cmd_check(args, con)


def cmd_check(args: argparse.Namespace, con: duckdb.DuckDBPyConnection | None = None) -> int:
    con = con or _connect(args.db)
    results = run_checks(con)
    for r in results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.name}: {r.detail}")
    return 0 if all(r.passed for r in results) else 1


def cmd_kpis(args: argparse.Namespace) -> int:
    con = _connect(args.db)
    period = latest_period(con)
    start, end = (period.start, period.end) if args.latest else (None, None)
    values = compute_kpis(con, args.depot, start, end)
    scope = f"{args.depot or 'Network'} · {period.label if args.latest else 'whole period'}"
    print(f"KPIs for {scope}")
    for key, value in values.items():
        kpi = KPIS[key]
        target = "" if kpi.target is None else format_value(kpi, kpi.target)
        print(
            f"  {kpi.label:<26} {format_value(kpi, value):>10}   "
            f"target {target:>8}   {rag_status(kpi, value)}"
        )
    return 0


def cmd_scorecard(args: argparse.Namespace) -> int:
    con = _connect(args.db)
    df = query_df(
        con,
        """SELECT depot_code, parcels, first_attempt_rate, on_time_rate, on_time_rate_mom, on_time_rank,
                  cost_per_parcel, vehicle_utilisation
           FROM v_depot_scorecard WHERE month_start = (SELECT MAX(month_start) FROM v_depot_scorecard)
           ORDER BY on_time_rank""",
    )
    df["parcels"] = df["parcels"].astype(int)
    print(df.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    pages = build_dashboard(_connect(args.db), args.out)
    print(f"Wrote {len(pages)} pages to {args.out} (open {pages[0]})")
    return 0


def cmd_charts(args: argparse.Namespace) -> int:
    for path in build_charts(_connect(args.db), args.out):
        print(f"Wrote {path}")
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    Path(args.out).write_text("# KPI definitions\n\n" + kpi_definitions_markdown(), encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="delivery-bi", description="Last-mile delivery operations BI.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"DuckDB file (default {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="generate data, build the warehouse and run quality checks")
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_build)
    sub.add_parser("check", help="run data quality and reconciliation checks").set_defaults(func=cmd_check)
    p = sub.add_parser("kpis", help="print KPIs with targets and RAG status")
    p.add_argument("--depot", help="depot code, e.g. BHM")
    p.add_argument("--latest", action="store_true", help="latest month only")
    p.set_defaults(func=cmd_kpis)
    sub.add_parser("scorecard", help="latest monthly depot scorecard").set_defaults(func=cmd_scorecard)
    p = sub.add_parser("dashboard", help="write the interactive HTML dashboard")
    p.add_argument("--out", type=Path, default=Path("dashboard"))
    p.set_defaults(func=cmd_dashboard)
    p = sub.add_parser("charts", help="write PNG charts")
    p.add_argument("--out", type=Path, default=Path("docs/images"))
    p.set_defaults(func=cmd_charts)
    p = sub.add_parser("docs", help="write the KPI catalogue as Markdown")
    p.add_argument("--out", type=Path, default=Path("docs/KPI_DEFINITIONS.md"))
    p.set_defaults(func=cmd_docs)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
