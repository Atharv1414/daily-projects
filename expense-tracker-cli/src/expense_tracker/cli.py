"""Command-line interface."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .models import CATEGORIES, Expense, ValidationError, parse_amount, parse_category, parse_month
from .reports import (
    budget_status,
    export_csv,
    money,
    over_budget_warnings,
    render_table,
    summary_table,
)
from .storage import Store

DEFAULT_DB = Path(os.environ.get("EXPENSE_DB", Path.home() / ".expense_tracker.db"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="expense", description="Track spending against monthly budgets."
    )
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Record an expense")
    add.add_argument("amount")
    add.add_argument("category", help=f"One of: {', '.join(CATEGORIES)}")
    add.add_argument("-n", "--note", default="")
    add.add_argument("-d", "--date", default=None, help="YYYY-MM-DD (default: today)")

    ls = sub.add_parser("list", help="List expenses")
    ls.add_argument("-m", "--month")
    ls.add_argument("-c", "--category")

    rm = sub.add_parser("delete", help="Delete an expense by id")
    rm.add_argument("id", type=int)

    bud = sub.add_parser("budget", help="Set a monthly budget for a category")
    bud.add_argument("category")
    bud.add_argument("amount")
    bud.add_argument("-m", "--month", default=None, help="YYYY-MM (default: this month)")

    summ = sub.add_parser("summary", help="Spending vs budget for a month")
    summ.add_argument("-m", "--month", default=None)

    exp = sub.add_parser("export", help="Export expenses to CSV")
    exp.add_argument("output", type=Path)
    exp.add_argument("-m", "--month")
    return p


def _this_month() -> str:
    return date.today().strftime("%Y-%m")


def run(argv: list[str] | None = None, store: Store | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = store or Store(args.db)
    try:
        return _dispatch(args, store)
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace, store: Store) -> int:
    if args.command == "add":
        try:
            spent_on = date.fromisoformat(args.date) if args.date else date.today()
        except ValueError as exc:
            raise ValidationError(f"Date must be YYYY-MM-DD, got {args.date!r}") from exc
        e = store.add_expense(
            Expense(parse_amount(args.amount), parse_category(args.category), spent_on, args.note)
        )
        print(f"Added #{e.id}: {money(e.amount)} on {e.category} ({e.spent_on})")
        warnings = over_budget_warnings(
            budget_status(store.list_expenses(month=e.month), store.get_budgets(e.month))
        )
        for w in warnings:
            if w.startswith(e.category + ":"):
                print(f"⚠️  Over budget — {w}")
        return 0

    if args.command == "list":
        month = parse_month(args.month) if args.month else None
        category = parse_category(args.category) if args.category else None
        rows = [
            [str(e.id), e.spent_on.isoformat(), e.category, money(e.amount), e.note]
            for e in store.list_expenses(month, category)
        ]
        if not rows:
            print("No expenses found.")
            return 0
        print(render_table(["ID", "Date", "Category", "Amount", "Note"], rows))
        return 0

    if args.command == "delete":
        if store.delete_expense(args.id):
            print(f"Deleted #{args.id}")
            return 0
        print(f"No expense with id {args.id}", file=sys.stderr)
        return 1

    if args.command == "budget":
        month = parse_month(args.month) if args.month else _this_month()
        category, amount = parse_category(args.category), parse_amount(args.amount)
        store.set_budget(month, category, amount)
        print(f"Budget for {category} in {month} set to {money(amount)}")
        return 0

    if args.command == "summary":
        month = parse_month(args.month) if args.month else _this_month()
        statuses = budget_status(store.list_expenses(month=month), store.get_budgets(month))
        if not statuses:
            print(f"No expenses or budgets for {month}.")
            return 0
        print(f"Summary for {month}\n")
        print(summary_table(statuses))
        for w in over_budget_warnings(statuses):
            print(f"⚠️  {w}")
        return 0

    if args.command == "export":
        month = parse_month(args.month) if args.month else None
        with args.output.open("w", newline="", encoding="utf-8") as fh:
            n = export_csv(store.list_expenses(month=month), fh)
        print(f"Exported {n} expenses to {args.output}")
        return 0

    return 1  # pragma: no cover


def main() -> None:  # pragma: no cover
    sys.exit(run())
