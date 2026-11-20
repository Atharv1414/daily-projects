import sqlite3
from contextlib import closing

import pytest

from expense_tracker.db import SCHEMA_VERSION, connect, migrate, schema_version, transaction
from expense_tracker.errors import MigrationError
from expense_tracker.repository import BudgetRepository, ExpenseRepository


def _legacy_v1_database(path):
    """Create a database exactly as Expense Tracker v1.0 wrote it (no user_version)."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, amount TEXT NOT NULL,
            category TEXT NOT NULL, spent_on TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
        CREATE INDEX idx_expenses_spent_on ON expenses(spent_on);
        CREATE TABLE budgets (month TEXT NOT NULL, category TEXT NOT NULL, amount TEXT NOT NULL,
            PRIMARY KEY (month, category));
        INSERT INTO expenses (amount, category, spent_on, note)
            VALUES ('12.50', 'food', '2026-11-03', 'Lunch'), ('0.10', 'other', '2026-11-04', '');
        INSERT INTO budgets VALUES ('2026-11', 'food', '200.00');
        """
    )
    conn.commit()
    conn.close()


def test_fresh_database_is_fully_migrated():
    with closing(connect(":memory:")) as conn:
        assert migrate(conn) == [1, 2, 3]
        assert schema_version(conn) == SCHEMA_VERSION
        assert migrate(conn) == []  # idempotent


def test_v1_database_is_upgraded_without_data_loss(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_v1_database(path)
    with closing(connect(path)) as conn:
        migrate(conn)
        expenses = list(ExpenseRepository(conn).iter())
        assert [(e.amount_pence, e.note) for e in expenses] == [(1250, "Lunch"), (10, "")]
        assert BudgetRepository(conn).for_month("2026-11") == {"food": 20000}


def test_newer_schema_is_refused():
    with closing(connect(":memory:")) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        with pytest.raises(MigrationError):
            migrate(conn)


def test_transaction_rolls_back_on_error(conn):
    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute("INSERT INTO budgets VALUES ('2026-11', 'food', 100)")
        raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0


def test_schema_enforces_positive_amounts(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO expenses (amount_pence, category, spent_on) "
            "VALUES (-5, 'food', '2026-01-01')"
        )
