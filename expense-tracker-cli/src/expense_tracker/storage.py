"""SQLite persistence layer."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import Expense

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    amount    TEXT    NOT NULL,
    category  TEXT    NOT NULL,
    spent_on  TEXT    NOT NULL,
    note      TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_expenses_spent_on ON expenses(spent_on);

CREATE TABLE IF NOT EXISTS budgets (
    month     TEXT NOT NULL,
    category  TEXT NOT NULL,
    amount    TEXT NOT NULL,
    PRIMARY KEY (month, category)
);
"""


class Store:
    """Thin repository over a SQLite database."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # --- expenses -------------------------------------------------------
    def add_expense(self, expense: Expense) -> Expense:
        cur = self.conn.execute(
            "INSERT INTO expenses (amount, category, spent_on, note) VALUES (?, ?, ?, ?)",
            (str(expense.amount), expense.category, expense.spent_on.isoformat(), expense.note),
        )
        self.conn.commit()
        return Expense(
            expense.amount, expense.category, expense.spent_on, expense.note, cur.lastrowid
        )

    def delete_expense(self, expense_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def list_expenses(self, month: str | None = None, category: str | None = None) -> list[Expense]:
        sql = "SELECT * FROM expenses WHERE 1=1"
        params: list[str] = []
        if month:
            sql += " AND substr(spent_on, 1, 7) = ?"
            params.append(month)
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY spent_on, id"
        return [self._row_to_expense(r) for r in self.conn.execute(sql, params)]

    @staticmethod
    def _row_to_expense(row: sqlite3.Row) -> Expense:
        return Expense(
            amount=Decimal(row["amount"]),
            category=row["category"],
            spent_on=date.fromisoformat(row["spent_on"]),
            note=row["note"],
            id=row["id"],
        )

    # --- budgets --------------------------------------------------------
    def set_budget(self, month: str, category: str, amount: Decimal) -> None:
        self.conn.execute(
            "INSERT INTO budgets (month, category, amount) VALUES (?, ?, ?) "
            "ON CONFLICT(month, category) DO UPDATE SET amount = excluded.amount",
            (month, category, str(amount)),
        )
        self.conn.commit()

    def get_budgets(self, month: str) -> dict[str, Decimal]:
        rows = self.conn.execute("SELECT category, amount FROM budgets WHERE month = ?", (month,))
        return {r["category"]: Decimal(r["amount"]) for r in rows}
