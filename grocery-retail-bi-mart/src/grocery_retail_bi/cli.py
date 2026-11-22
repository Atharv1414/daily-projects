"""bi-mart: generate sources, build the warehouse, query metrics, render dashboards, validate."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from grocery_retail_bi.charts import build_charts
from grocery_retail_bi.dashboard import build_dashboard
from grocery_retail_bi.datagen import GenConfig, generate
from grocery_retail_bi.models import ordered
from grocery_retail_bi.security import USERS, AccessDenied, get_user
from grocery_retail_bi.semantic import DIMENSIONS, METRICS, SemanticError, fmt_value, query
from grocery_retail_bi.validation import report, run_checks
from grocery_retail_bi.warehouse import WarehouseError, build, connect

RAW = Path("data/raw")
DB = Path("data/harvest.duckdb")
CUTOFFS = [datetime(2026, 6, 30), datetime(2026, 9, 30)]


def _ensure_built(args) -> None:
    if not (RAW / "sales_lines.csv").exists():
        generate(GenConfig(out_dir=RAW))
    if not DB.exists() or args.rebuild:
        conn, stats = build(RAW, DB, CUTOFFS)
        conn.close()


def cmd_generate(args) -> int:
    paths = generate(GenConfig(out_dir=RAW, n_baskets=args.baskets))
    for name, p in paths.items():
        print(f"{name:<11} {p}  ({p.stat().st_size / 1e6:.1f} MB)")
    return 0


def cmd_build(args) -> int:
    if not (RAW / "sales_lines.csv").exists():
        generate(GenConfig(out_dir=RAW))
    conn, stats = build(RAW, DB, CUTOFFS)
    print("Raw rows:", json.dumps(stats["raw_rows"]))
    print("Models built (dependency order):", ", ".join(stats["models"]))
    for b in stats["batches"]:
        print(
            f"  batch {b['batch_id']}: loaded_at > {b['watermark_from']:%Y-%m-%d %H:%M} -> "
            f"{b['rows_inserted']:,} rows ({b['late_rows']:,} late-arriving)"
        )
    print(f"Fact rows: {stats['fact_rows']:,} · timings (s): {stats['timings_s']}")
    conn.close()
    return 0


def cmd_query(args) -> int:
    _ensure_built(args)
    conn = connect(DB)
    filters = {}
    for f in args.filter or []:
        dim, _, values = f.partition("=")
        filters[dim] = values.split(",")
    df = query(
        conn,
        args.metrics,
        get_user(args.user),
        args.by or [],
        filters,
        date.fromisoformat(args.date_from) if args.date_from else None,
        date.fromisoformat(args.date_to) if args.date_to else None,
    )
    for m in args.metrics:
        df[m] = [fmt_value(m, v) for v in df[m]]
    print(df.to_string(index=False) if len(df) else "(no rows visible to this user)")
    return 0


def cmd_dashboard(args) -> int:
    _ensure_built(args)
    conn = connect(DB)
    for username in args.users:
        res = build_dashboard(conn, get_user(username), Path(args.out))
        print(
            f"{username:<15} -> {res.pages[0].parent}/ ({len(res.pages)} pages) · L12M net "
            f"sales {fmt_value('net_sales', res.kpis['net_sales'])}, vs target "
            f"{fmt_value('vs_target_pct', res.kpis['vs_target_pct'])}, LFL "
            f"{fmt_value('lfl_growth', res.kpis['lfl_growth_ytd'])}"
        )
    return 0


def cmd_validate(args) -> int:
    _ensure_built(args)
    conn = connect(DB)
    kpis = build_dashboard(conn, USERS["ceo"], Path(args.out)).kpis
    checks = run_checks(conn, kpis)
    text = report(checks)
    print(text)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text("# Validation report\n\n" + text + "\n", encoding="utf-8")
    return 0 if all(c.passed or c.severity == "warn" for c in checks) else 1


def cmd_charts(args) -> int:
    _ensure_built(args)
    for p in build_charts(connect(DB), Path(args.out)):
        print(p)
    return 0


def cmd_catalog(args) -> int:
    print("Metrics:")
    for m in METRICS.values():
        print(f"  {m.name:<18} {m.fmt:<4} {m.description}")
    print("\nDimensions:")
    for name, (_, facts, desc) in DIMENSIONS.items():
        print(f"  {name:<14} [{', '.join(sorted(facts))}] {desc}")
    print("\nModels:")
    for model in ordered():
        print(f"  {model.name:<30} {model.kind:<5} {model.grain}")
    print("\nUsers:", ", ".join(USERS))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bi-mart", description=__doc__)
    p.add_argument("--rebuild", action="store_true", help="Force a warehouse rebuild")
    sub = p.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate", help="Write seeded source extracts to data/raw")
    g.add_argument("--baskets", type=int, default=120_000)
    sub.add_parser("build", help="Land raw, run models, load facts in incremental batches")
    q = sub.add_parser("query", help="Query the semantic layer as a user")
    q.add_argument("metrics", nargs="+")
    q.add_argument("--by", nargs="*")
    q.add_argument("--filter", action="append", help="dim=value1,value2")
    q.add_argument("--user", default="ceo")
    q.add_argument("--date-from")
    q.add_argument("--date-to")
    d = sub.add_parser("dashboard", help="Render per-user dashboards")
    d.add_argument("--users", nargs="+", default=["ceo", "rm_north_west", "sm_s105"])
    d.add_argument("--out", default="dashboard")
    v = sub.add_parser("validate", help="Reconcile dashboard numbers to source")
    v.add_argument("--out", default="dashboard")
    v.add_argument("--report", default="docs/VALIDATION.md")
    c = sub.add_parser("charts", help="Write PNG charts")
    c.add_argument("--out", default="docs/charts")
    sub.add_parser("catalog", help="List metrics, dimensions, models and users")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = build_parser().parse_args(argv)
    handlers = {
        "generate": cmd_generate,
        "build": cmd_build,
        "query": cmd_query,
        "dashboard": cmd_dashboard,
        "validate": cmd_validate,
        "charts": cmd_charts,
        "catalog": cmd_catalog,
    }
    try:
        return handlers[args.command](args)
    except (SemanticError, AccessDenied, WarehouseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
