"""Command-line interface (argparse). Thin layer: parse input, call the service, print."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from . import __version__
from .bench import run_benchmark
from .config import Settings
from .datagen import write_sample_statements
from .db import SCHEMA_VERSION, schema_version
from .errors import ExpenseTrackerError
from .logging_setup import configure_logging
from .models import CATEGORIES, FREQUENCIES, RecurringRule, parse_category, parse_date, parse_month
from .money import parse_money
from .reports import (
    anomaly_table,
    export_csv,
    export_json,
    html_report,
    render_table,
    summary_table,
    trend_table,
)
from .repository import ExpenseFilter
from .service import ExpenseTracker

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="expense",
        description="Track spending, import bank statements and stay within monthly budgets.",
    )
    p.add_argument("--db", type=Path, help="SQLite database path (env: EXPENSE_DB)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    add = sub.add_parser("add", help="record an expense")
    add.add_argument("amount")
    add.add_argument("category", nargs="?", help="omit to auto-categorise from --merchant")
    add.add_argument("-m", "--merchant", default="")
    add.add_argument("-n", "--note", default="")
    add.add_argument("-d", "--date", help="YYYY-MM-DD or DD/MM/YYYY (default: today)")

    ls = sub.add_parser("list", help="search expenses with filters and pagination")
    ls.add_argument("--month")
    ls.add_argument("-c", "--category")
    ls.add_argument("--merchant")
    ls.add_argument("--min")
    ls.add_argument("--max")
    ls.add_argument("--source", choices=["manual", "import", "recurring"])
    ls.add_argument("--sort", choices=["date", "-date", "amount"], default="date")
    ls.add_argument("--page", type=int, default=1)
    ls.add_argument("--page-size", type=int, default=25)

    rm = sub.add_parser("delete", help="delete an expense by id")
    rm.add_argument("id", type=int)

    bud = sub.add_parser("budget", help="set a monthly budget for a category")
    bud.add_argument("category")
    bud.add_argument("amount")
    bud.add_argument("--month", help="YYYY-MM (default: this month)")

    roll = sub.add_parser("budget-rollover", help="copy last month's budgets into a month")
    roll.add_argument("--month", help="YYYY-MM (default: this month)")

    imp = sub.add_parser("import", help="import a bank statement CSV")
    imp.add_argument("file", type=Path)
    imp.add_argument("--quarantine", type=Path, help="write rejected rows to this CSV")

    sub.add_parser("imports", help="show the import audit log")

    rec = sub.add_parser("recurring", help="manage recurring expenses")
    rec_sub = rec.add_subparsers(dest="recurring_command", required=True)
    rec_add = rec_sub.add_parser("add")
    rec_add.add_argument("name")
    rec_add.add_argument("amount")
    rec_add.add_argument("category")
    rec_add.add_argument("--frequency", choices=FREQUENCIES, default="monthly")
    rec_add.add_argument("--start", required=True)
    rec_add.add_argument("--end")
    rec_add.add_argument("--merchant", default="")
    rec_sub.add_parser("list")
    rec_run = rec_sub.add_parser("run", help="create any due recurring expenses")
    rec_run.add_argument("--until", help="default: today")

    rules = sub.add_parser("rule", help="add an auto-categorisation rule (regex on merchant)")
    rules.add_argument("pattern")
    rules.add_argument("category")
    rules.add_argument("--priority", type=int, default=100)

    summ = sub.add_parser("summary", help="spending vs budget, with month-end projection")
    summ.add_argument("--month")

    tr = sub.add_parser("trend", help="monthly totals with change and rolling average")
    tr.add_argument("--months", type=int, default=6)
    tr.add_argument("--month", help="last month to include (default: this month)")

    an = sub.add_parser("anomalies", help="unusually large expenses per category")
    an.add_argument("--month")

    exp = sub.add_parser("export", help="export expenses to CSV or JSON")
    exp.add_argument("output", type=Path)
    exp.add_argument("--month")
    exp.add_argument("--format", choices=["csv", "json"])

    rep = sub.add_parser("report", help="write a self-contained HTML report")
    rep.add_argument("output", type=Path)
    rep.add_argument("--month")

    gen = sub.add_parser("generate-data", help="write sample bank statements")
    gen.add_argument("out_dir", type=Path)
    gen.add_argument("--seed", type=int, default=42)

    bench = sub.add_parser("bench", help="benchmark import and analytics")
    bench.add_argument("--rows", type=int, default=100_000)

    sub.add_parser("db-info", help="show database path, schema version and row count")
    return p


def run(
    argv: Sequence[str] | None = None,
    tracker: ExpenseTracker | None = None,
    today: date | None = None,
    settings: Settings | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    today = today or date.today()
    try:
        if args.command == "generate-data":
            for path in write_sample_statements(args.out_dir, seed=args.seed):
                print(f"Wrote {path}")
            return 0
        if args.command == "bench":
            return _bench(args.rows)
        own = tracker is None
        if tracker is None:
            settings = settings or Settings.from_env()
            if args.db:
                settings = Settings(**{**settings.__dict__, "db_path": args.db})
            tracker = ExpenseTracker.open(settings)
        try:
            return _dispatch(args, tracker, today)
        finally:
            if own:
                tracker.close()
    except ExpenseTrackerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


def _month(value: str | None, today: date) -> str:
    return parse_month(value) if value else today.strftime("%Y-%m")


def _dispatch(args: argparse.Namespace, t: ExpenseTracker, today: date) -> int:  # noqa: C901
    cmd = args.command
    if cmd == "add":
        result = t.add_expense(
            parse_money(args.amount),
            parse_date(args.date) if args.date else today,
            parse_category(args.category) if args.category else None,
            args.merchant,
            args.note,
            today=today,
        )
        e = result.expense
        where = f" at {e.merchant}" if e.merchant else ""
        how = "" if result.category_reason == "manual" else f" (auto: {result.category_reason})"
        print(
            f"Added #{e.id}: {t.money(e.amount_pence)} on {e.category}{how}{where} ({e.spent_on})"
        )
        for w in result.warnings:
            print(f"⚠️  {w}")
    elif cmd == "list":
        flt = ExpenseFilter(
            month=parse_month(args.month) if args.month else None,
            category=parse_category(args.category) if args.category else None,
            merchant=args.merchant,
            min_pence=parse_money(args.min) if args.min else None,
            max_pence=parse_money(args.max) if args.max else None,
            source=args.source,
        )
        page = t.expenses.search(flt, page=args.page, page_size=args.page_size, order=args.sort)
        if not page.items:
            print("No expenses found.")
            return 0
        rows = [
            [str(e.id), e.spent_on.isoformat(), e.category, e.merchant, t.money(e.amount_pence)]
            for e in page.items
        ]
        print(render_table(["ID", "Date", "Category", "Merchant", "Amount"], rows))
        print(f"\nPage {page.page} of {page.pages} · {page.total} matching expenses")
    elif cmd == "delete":
        t.expenses.delete(args.id)
        print(f"Deleted #{args.id}")
    elif cmd == "budget":
        month = _month(args.month, today)
        amount = parse_money(args.amount)
        t.set_budget(month, parse_category(args.category), amount)
        print(f"Budget for {args.category.lower()} in {month} set to {t.money(amount)}")
    elif cmd == "budget-rollover":
        month = _month(args.month, today)
        print(f"Copied {t.roll_budgets_forward(month)} budget(s) into {month}")
    elif cmd == "import":
        r = t.import_statement(args.file, args.quarantine)
        print(
            f"Imported {args.file.name}: {r.rows_read} rows read, {r.inserted} new expenses, "
            f"{r.duplicates} duplicates skipped, {r.credits_skipped} credits ignored, "
            f"{len(r.rejected)} rejected"
        )
        for rej in r.rejected[:5]:
            print(f"  line {rej.line}: {rej.reason}")
        if args.quarantine and r.rejected:
            print(f"Rejected rows written to {args.quarantine}")
    elif cmd == "imports":
        runs = t.import_runs.list()
        rows = [
            [str(r.id), r.started_at, r.status, Path(r.source_file).name]
            + [str(r.counts[k]) for k in ("rows_read", "inserted", "duplicates", "rejected")]
            for r in runs
        ]
        print(
            render_table(["Run", "Started", "Status", "File", "Read", "New", "Dupes", "Bad"], rows)
        )
    elif cmd == "recurring":
        return _recurring(args, t, today)
    elif cmd == "rule":
        rule = t.add_category_rule(args.pattern, parse_category(args.category), args.priority)
        print(f"Rule #{rule.id}: merchants matching {rule.pattern!r} -> {rule.category}")
    elif cmd == "summary":
        month = _month(args.month, today)
        statuses = t.summary(month, today)
        if not statuses:
            print(f"No expenses or budgets for {month}.")
            return 0
        print(f"Summary for {month}\n")
        print(summary_table(statuses, t.money))
        for w in t.warnings(statuses):
            print(f"⚠️  {w}")
    elif cmd == "trend":
        print(trend_table(t.trend(args.months, _month(args.month, today)), t.money))
    elif cmd == "anomalies":
        found = t.anomalies(parse_month(args.month) if args.month else None)
        print(anomaly_table(found, t.money) if found else "No unusual expenses found.")
    elif cmd == "export":
        fmt = args.format or ("json" if args.output.suffix.lower() == ".json" else "csv")
        flt = ExpenseFilter(month=parse_month(args.month) if args.month else None)
        with args.output.open("w", newline="", encoding="utf-8") as fh:
            n = (export_json if fmt == "json" else export_csv)(t.expenses.iter(flt), fh)
        print(f"Exported {n} expenses to {args.output}")
    elif cmd == "report":
        month = _month(args.month, today)
        page = html_report(
            month,
            t.summary(month, today),
            t.trend(12, month),
            t.anomalies(),
            t.top_merchants(month),
            t.money,
        )
        args.output.write_text(page, encoding="utf-8")
        print(f"Wrote report for {month} to {args.output}")
    elif cmd == "db-info":
        print(f"Database: {t.settings.db_path}")
        print(f"Schema:   v{schema_version(t.conn)} (latest v{SCHEMA_VERSION})")
        print(f"Expenses: {t.expenses.count():,}")
    return 0


def _recurring(args: argparse.Namespace, t: ExpenseTracker, today: date) -> int:
    if args.recurring_command == "add":
        rule = t.add_recurring(
            RecurringRule(
                name=args.name,
                amount_pence=parse_money(args.amount),
                category=parse_category(args.category),
                frequency=args.frequency,
                start_date=parse_date(args.start),
                merchant=args.merchant,
                end_date=parse_date(args.end) if args.end else None,
            )
        )
        print(f"Recurring #{rule.id}: {rule.name} {t.money(rule.amount_pence)} {rule.frequency}")
    elif args.recurring_command == "list":
        rows = [
            [
                str(r.id),
                r.name,
                t.money(r.amount_pence),
                r.category,
                r.frequency,
                r.start_date.isoformat(),
                r.end_date.isoformat() if r.end_date else "-",
            ]
            for r in t.recurring_rules.list()
        ]
        print(render_table(["ID", "Name", "Amount", "Category", "Every", "From", "Until"], rows))
    else:
        until = parse_date(args.until) if args.until else today
        print(f"Created {t.materialise_recurring(until)} recurring expense(s) up to {until}")
    return 0


def _bench(rows: int) -> int:
    result = run_benchmark(rows)
    print(f"Benchmark: {result.rows:,} statement rows ({result.inserted:,} expenses)\n")
    print(
        render_table(
            ["Step", "Seconds"],
            [[name, f"{secs:.3f}"] for name, secs in result.timings.items()],
        )
    )
    print(f"\nImport throughput: {result.import_rows_per_sec:,.0f} rows/sec")
    return 0


def main() -> None:  # pragma: no cover
    settings = Settings.from_env()
    configure_logging(settings.log_level, settings.log_json)
    sys.exit(run(settings=settings))


__all__ = ["CATEGORIES", "build_parser", "main", "run"]
