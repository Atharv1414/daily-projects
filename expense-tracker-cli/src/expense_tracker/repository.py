"""Repositories: the only place that knows SQL.

All queries are parameterised. Aggregations (totals by category/month, merchant history,
top merchants) are pushed down into SQLite rather than done in Python, so they stay fast on
hundreds of thousands of rows.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .db import transaction
from .errors import NotFoundError, ValidationError
from .models import Budget, CategoryRule, Expense, RecurringRule, month_bounds

_ORDERS = {
    "date": "spent_on ASC, id ASC",
    "-date": "spent_on DESC, id DESC",
    "amount": "amount_pence DESC, id ASC",
}
_BATCH_SIZE = 5_000


@dataclass(frozen=True)
class ExpenseFilter:
    month: str | None = None
    start: date | None = None
    end: date | None = None
    category: str | None = None
    merchant: str | None = None
    min_pence: int | None = None
    max_pence: int | None = None
    source: str | None = None

    def to_sql(self) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if self.month:
            first, last = month_bounds(self.month)
            clauses.append("spent_on BETWEEN ? AND ?")
            params += [first.isoformat(), last.isoformat()]
        if self.start:
            clauses.append("spent_on >= ?")
            params.append(self.start.isoformat())
        if self.end:
            clauses.append("spent_on <= ?")
            params.append(self.end.isoformat())
        if self.category:
            clauses.append("category = ?")
            params.append(self.category)
        if self.merchant:
            clauses.append("merchant LIKE ? ESCAPE '\\'")
            escaped = self.merchant.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        if self.min_pence is not None:
            clauses.append("amount_pence >= ?")
            params.append(self.min_pence)
        if self.max_pence is not None:
            clauses.append("amount_pence <= ?")
            params.append(self.max_pence)
        if self.source:
            clauses.append("source = ?")
            params.append(self.source)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


@dataclass(frozen=True)
class Page:
    items: list[Expense]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.total / self.page_size))


@dataclass(frozen=True)
class MerchantStat:
    merchant: str
    count: int
    total_pence: int


def _to_expense(row: sqlite3.Row) -> Expense:
    return Expense(
        amount_pence=row["amount_pence"],
        category=row["category"],
        spent_on=date.fromisoformat(row["spent_on"]),
        merchant=row["merchant"],
        note=row["note"],
        source=row["source"],
        import_hash=row["import_hash"],
        id=row["id"],
    )


def _expense_params(e: Expense) -> tuple[Any, ...]:
    return (
        e.amount_pence,
        e.category,
        e.spent_on.isoformat(),
        e.merchant,
        e.note,
        e.source,
        e.import_hash,
    )


_INSERT_EXPENSE = (
    "INSERT {mode} INTO expenses "
    "(amount_pence, category, spent_on, merchant, note, source, import_hash) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)


@dataclass
class ExpenseRepository:
    conn: sqlite3.Connection

    def add(self, expense: Expense) -> Expense:
        try:
            cur = self.conn.execute(_INSERT_EXPENSE.format(mode=""), _expense_params(expense))
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Duplicate expense: {exc}") from exc
        return self.get(cur.lastrowid)

    def add_many(self, expenses: Iterable[Expense]) -> int:
        """Insert in batches inside one transaction, skipping rows whose import_hash exists.

        Returns the number of rows actually inserted (duplicates are silently ignored, which
        is what makes re-importing the same statement safe).
        """
        sql = _INSERT_EXPENSE.format(mode="OR IGNORE")
        before = self.conn.total_changes
        with transaction(self.conn):
            batch: list[tuple[Any, ...]] = []
            for expense in expenses:
                batch.append(_expense_params(expense))
                if len(batch) >= _BATCH_SIZE:
                    self.conn.executemany(sql, batch)
                    batch.clear()
            if batch:
                self.conn.executemany(sql, batch)
        return self.conn.total_changes - before

    def get(self, expense_id: int) -> Expense:
        row = self.conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"No expense with id {expense_id}")
        return _to_expense(row)

    def delete(self, expense_id: int) -> None:
        cur = self.conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        if cur.rowcount == 0:
            raise NotFoundError(f"No expense with id {expense_id}")

    def search(
        self,
        flt: ExpenseFilter = ExpenseFilter(),  # noqa: B008 - frozen, safe as default
        *,
        page: int = 1,
        page_size: int = 50,
        order: str = "date",
    ) -> Page:
        if page < 1 or not 1 <= page_size <= 1000:
            raise ValidationError("page must be >= 1 and page_size between 1 and 1000")
        if order not in _ORDERS:
            raise ValidationError(f"order must be one of {sorted(_ORDERS)}")
        where, params = flt.to_sql()
        total = self.conn.execute(f"SELECT COUNT(*) FROM expenses{where}", params).fetchone()[0]
        rows = self.conn.execute(
            f"SELECT * FROM expenses{where} ORDER BY {_ORDERS[order]} LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return Page([_to_expense(r) for r in rows], total, page, page_size)

    def iter(self, flt: ExpenseFilter = ExpenseFilter()) -> Iterator[Expense]:  # noqa: B008
        where, params = flt.to_sql()
        for row in self.conn.execute(
            f"SELECT * FROM expenses{where} ORDER BY spent_on, id", params
        ):
            yield _to_expense(row)

    def totals_by_category(self, flt: ExpenseFilter = ExpenseFilter()) -> dict[str, int]:  # noqa: B008
        where, params = flt.to_sql()
        rows = self.conn.execute(
            f"SELECT category, SUM(amount_pence) AS total FROM expenses{where} "
            "GROUP BY category ORDER BY total DESC",
            params,
        )
        return {r["category"]: r["total"] for r in rows}

    def totals_by_month(self, flt: ExpenseFilter = ExpenseFilter()) -> dict[str, int]:  # noqa: B008
        where, params = flt.to_sql()
        rows = self.conn.execute(
            f"SELECT substr(spent_on, 1, 7) AS month, SUM(amount_pence) AS total "
            f"FROM expenses{where} GROUP BY month ORDER BY month",
            params,
        )
        return {r["month"]: r["total"] for r in rows}

    def merchant_category_history(self) -> dict[str, str]:
        """Most frequent category per merchant (ties broken alphabetically)."""
        rows = self.conn.execute(
            """
            SELECT merchant, category FROM (
                SELECT merchant, category,
                       ROW_NUMBER() OVER (
                           PARTITION BY merchant ORDER BY COUNT(*) DESC, category
                       ) AS rn
                FROM expenses
                WHERE merchant <> ''
                GROUP BY merchant, category
            ) WHERE rn = 1
            """
        )
        return {r["merchant"]: r["category"] for r in rows}

    def top_merchants(
        self,
        flt: ExpenseFilter = ExpenseFilter(),  # noqa: B008
        limit: int = 10,
    ) -> list[MerchantStat]:
        where, params = flt.to_sql()
        rows = self.conn.execute(
            f"SELECT merchant, COUNT(*) AS n, SUM(amount_pence) AS total FROM expenses{where} "
            "GROUP BY merchant ORDER BY total DESC LIMIT ?",
            [*params, limit],
        )
        return [MerchantStat(r["merchant"] or "(none)", r["n"], r["total"]) for r in rows]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]


@dataclass
class BudgetRepository:
    conn: sqlite3.Connection

    def set(self, budget: Budget) -> None:
        self.conn.execute(
            "INSERT INTO budgets (month, category, amount_pence) VALUES (?, ?, ?) "
            "ON CONFLICT (month, category) DO UPDATE SET amount_pence = excluded.amount_pence",
            (budget.month, budget.category, budget.amount_pence),
        )

    def for_month(self, month: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT category, amount_pence FROM budgets WHERE month = ?", (month,)
        )
        return {r["category"]: r["amount_pence"] for r in rows}

    def copy_month(self, source: str, target: str) -> int:
        """Roll budgets forward to a new month without overwriting ones already set."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO budgets (month, category, amount_pence) "
            "SELECT ?, category, amount_pence FROM budgets WHERE month = ?",
            (target, source),
        )
        return cur.rowcount


@dataclass
class RecurringRuleRepository:
    conn: sqlite3.Connection

    def add(self, rule: RecurringRule) -> RecurringRule:
        try:
            cur = self.conn.execute(
                "INSERT INTO recurring_rules "
                "(name, amount_pence, category, merchant, frequency, start_date, end_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    rule.name,
                    rule.amount_pence,
                    rule.category,
                    rule.merchant,
                    rule.frequency,
                    rule.start_date.isoformat(),
                    rule.end_date.isoformat() if rule.end_date else None,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"A recurring rule named {rule.name!r} already exists") from exc
        return RecurringRule(
            rule.name,
            rule.amount_pence,
            rule.category,
            rule.frequency,
            rule.start_date,
            rule.merchant,
            rule.end_date,
            cur.lastrowid,
        )

    def list(self) -> list[RecurringRule]:
        rows = self.conn.execute("SELECT * FROM recurring_rules ORDER BY id")
        return [
            RecurringRule(
                r["name"],
                r["amount_pence"],
                r["category"],
                r["frequency"],
                date.fromisoformat(r["start_date"]),
                r["merchant"],
                date.fromisoformat(r["end_date"]) if r["end_date"] else None,
                r["id"],
            )
            for r in rows
        ]


@dataclass
class CategoryRuleRepository:
    conn: sqlite3.Connection

    def add(self, rule: CategoryRule) -> CategoryRule:
        try:
            cur = self.conn.execute(
                "INSERT INTO category_rules (pattern, category, priority) VALUES (?, ?, ?)",
                (rule.pattern, rule.category, rule.priority),
            )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Rule {rule.pattern!r} already exists") from exc
        return CategoryRule(rule.pattern, rule.category, rule.priority, cur.lastrowid)

    def list(self) -> list[CategoryRule]:
        rows = self.conn.execute("SELECT * FROM category_rules ORDER BY priority, id")
        return [CategoryRule(r["pattern"], r["category"], r["priority"], r["id"]) for r in rows]


@dataclass
class ImportRun:
    id: int
    source_file: str
    started_at: str
    finished_at: str | None
    status: str
    counts: dict[str, int] = field(default_factory=dict)


_RUN_COUNTS = ("rows_read", "inserted", "duplicates", "credits_skipped", "rejected")


@dataclass
class ImportRunRepository:
    conn: sqlite3.Connection

    def start(self, source_file: str) -> int:
        cur = self.conn.execute("INSERT INTO import_runs (source_file) VALUES (?)", (source_file,))
        return cur.lastrowid

    def finish(self, run_id: int, status: str, counts: dict[str, int]) -> None:
        self.conn.execute(
            "UPDATE import_runs SET status = ?, "
            "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
            + ", ".join(f"{c} = ?" for c in _RUN_COUNTS)
            + " WHERE id = ?",
            (status, *(counts.get(c, 0) for c in _RUN_COUNTS), run_id),
        )

    def list(self, limit: int = 20) -> list[ImportRun]:
        rows = self.conn.execute("SELECT * FROM import_runs ORDER BY id DESC LIMIT ?", (limit,))
        return [
            ImportRun(
                r["id"],
                r["source_file"],
                r["started_at"],
                r["finished_at"],
                r["status"],
                {c: r[c] for c in _RUN_COUNTS},
            )
            for r in rows
        ]
