"""Micro-benchmark: import and analyse a large synthetic statement in an in-memory database."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

from .analytics import detect_anomalies, monthly_trend
from .categorizer import Categorizer
from .datagen import generate_transactions
from .db import open_database
from .importer import StatementImporter
from .repository import ExpenseFilter, ExpenseRepository, ImportRunRepository


@dataclass(frozen=True)
class BenchResult:
    rows: int
    inserted: int
    timings: dict[str, float]

    @property
    def import_rows_per_sec(self) -> float:
        return self.rows / self.timings["import"] if self.timings["import"] else float("inf")


def run_benchmark(target_rows: int = 100_000, seed: int = 7) -> BenchResult:
    # ~69 rows per generated month, so size the history to hit the target.
    months = max(1, round(target_rows / 69))
    rows = generate_transactions(date(2000, 1, 1), months, seed)
    conn = open_database(":memory:")
    expenses = ExpenseRepository(conn)
    importer = StatementImporter(expenses, ImportRunRepository(conn), Categorizer())
    timings: dict[str, float] = {}

    def timed(name, fn):
        t0 = time.perf_counter()
        out = fn()
        timings[name] = time.perf_counter() - t0
        return out

    result = timed(
        "import", lambda: importer.import_rows(rows, ["Date", "Description", "Amount"], "bench")
    )
    timed(
        "reimport_noop",
        lambda: importer.import_rows(rows, ["Date", "Description", "Amount"], "bench"),
    )
    month = max(expenses.totals_by_month())
    timed("month_summary", lambda: expenses.totals_by_category(ExpenseFilter(month=month)))
    timed("trend", lambda: monthly_trend(expenses.totals_by_month()))
    timed("merchant_history", expenses.merchant_category_history)
    timed("anomalies", lambda: detect_anomalies(expenses.iter()))
    conn.close()
    return BenchResult(len(rows), result.inserted, timings)
