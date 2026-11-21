"""``meterlake`` command line: generate · run · status · report · query · dag."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from smart_meter_lakehouse.config import PipelineConfig
from smart_meter_lakehouse.datagen import START_DATE, generate_landing
from smart_meter_lakehouse.errors import PipelineError
from smart_meter_lakehouse.pipeline import build_dag, run_pipeline
from smart_meter_lakehouse.report import run_summary, write_report
from smart_meter_lakehouse.warehouse import connect


def _print_rows(con, sql: str, params: list | None = None) -> None:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    widths = [
        max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(c)
        for i, c in enumerate(cols)
    ]
    print("  ".join(str(c).ljust(w) for c, w in zip(cols, widths, strict=True)))
    for r in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths, strict=True)))


def cmd_generate(args, cfg: PipelineConfig) -> int:
    t = time.perf_counter()
    s = generate_landing(cfg.landing_dir, meters=args.meters, days=args.days, seed=args.seed)
    print(
        f"landing zone: {s.files} files, {s.reading_rows:,} reading rows, "
        f"{s.customer_events:,} CDC events for {s.meters:,} meters over {s.days} days "
        f"({time.perf_counter() - t:.1f}s)"
    )
    return 0


def cmd_run(args, cfg: PipelineConfig) -> int:
    if args.flaky:
        cfg = replace(cfg, flaky_tariff_failures=args.flaky)
    con = connect(cfg.warehouse_path)
    try:
        t = time.perf_counter()
        result, ctx = run_pipeline(
            con, cfg, date.fromisoformat(args.through), full_refresh=args.full_refresh
        )
        print(run_summary(result, ctx))
        print(f"  total {time.perf_counter() - t:.2f}s")
    finally:
        con.close()
    return 0 if result.ok else 1


def cmd_status(args, cfg: PipelineConfig) -> int:
    con = connect(cfg.warehouse_path)
    try:
        print("watermarks:")
        _print_rows(con, "SELECT source, high_watermark FROM meta.watermarks ORDER BY 1")
        print("\nrecent runs:")
        _print_rows(
            con,
            "SELECT run_id, through_date, status FROM meta.dag_runs "
            "ORDER BY started_at DESC LIMIT 5",
        )
        print("\nlineage (latest successful run):")
        _print_rows(
            con,
            """SELECT task, input_table, output_table FROM meta.lineage
                            WHERE run_id = (SELECT run_id FROM meta.dag_runs
                                            WHERE status = 'success'
                                            ORDER BY started_at DESC LIMIT 1)""",
        )
    finally:
        con.close()
    return 0


def cmd_report(args, cfg: PipelineConfig) -> int:
    con = connect(cfg.warehouse_path)
    try:
        path = write_report(con, cfg.reports_dir)
        print(path.read_text())
        print(f"written to {path.parent}/")
    finally:
        con.close()
    return 0


def cmd_query(args, cfg: PipelineConfig) -> int:
    con = connect(cfg.warehouse_path)
    try:
        _print_rows(con, args.sql)
    finally:
        con.close()
    return 0


def cmd_dag(args, cfg: PipelineConfig) -> int:
    con = connect(":memory:")
    print(build_dag(con, cfg).to_mermaid())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="meterlake", description=__doc__)
    p.add_argument("--log-level", default="WARNING")
    sub = p.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate", help="write a seeded landing zone")
    g.add_argument("--meters", type=int, default=1_000)
    g.add_argument("--days", type=int, default=28)
    g.add_argument("--seed", type=int, default=7)
    g.set_defaults(func=cmd_generate)
    r = sub.add_parser("run", help="run the DAG for files dated up to --through")
    r.add_argument("--through", default=START_DATE.isoformat())
    r.add_argument("--full-refresh", action="store_true", help="rebuild every gold date")
    r.add_argument("--flaky", type=int, default=0, help="simulate N tariff API failures")
    r.set_defaults(func=cmd_run)
    sub.add_parser("status", help="watermarks, runs, lineage").set_defaults(func=cmd_status)
    sub.add_parser("report", help="DQ report + charts").set_defaults(func=cmd_report)
    q = sub.add_parser("query", help="run SQL against the warehouse")
    q.add_argument("sql")
    q.set_defaults(func=cmd_query)
    sub.add_parser("dag", help="print the DAG as Mermaid").set_defaults(func=cmd_dag)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")
    try:
        return args.func(args, PipelineConfig.from_env())
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
