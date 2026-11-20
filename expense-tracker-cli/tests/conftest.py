from datetime import date

import pytest

from expense_tracker.config import Settings
from expense_tracker.db import open_database
from expense_tracker.models import Expense
from expense_tracker.service import ExpenseTracker

TODAY = date(2026, 11, 15)


@pytest.fixture
def conn():
    c = open_database(":memory:")
    yield c
    c.close()


@pytest.fixture
def tracker(conn):
    return ExpenseTracker(conn, Settings(db_path=":memory:"))


def make_expense(pence=1000, category="food", day="2026-11-05", merchant="Tesco", **kw):
    return Expense(pence, category, date.fromisoformat(day), merchant, **kw)
