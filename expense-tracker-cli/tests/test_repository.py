from datetime import date

import pytest

from expense_tracker.errors import NotFoundError, ValidationError
from expense_tracker.models import Budget
from expense_tracker.repository import BudgetRepository, ExpenseFilter, ExpenseRepository

from .conftest import make_expense


@pytest.fixture
def repo(conn):
    r = ExpenseRepository(conn)
    r.add(make_expense(1000, "food", "2026-10-30", "Tesco"))
    r.add(make_expense(2500, "food", "2026-11-02", "Sainsburys"))
    r.add(make_expense(700, "transport", "2026-11-03", "Tfl"))
    r.add(make_expense(9900, "shopping", "2026-11-20", "100%_Deals"))
    return r


def test_get_and_delete(repo):
    assert repo.get(2).merchant == "Sainsburys"
    repo.delete(2)
    with pytest.raises(NotFoundError):
        repo.get(2)
    with pytest.raises(NotFoundError):
        repo.delete(2)


@pytest.mark.parametrize(
    ("flt", "expected_ids"),
    [
        (ExpenseFilter(month="2026-11"), [2, 3, 4]),
        (ExpenseFilter(category="food"), [1, 2]),
        (ExpenseFilter(start=date(2026, 11, 3), end=date(2026, 11, 30)), [3, 4]),
        (ExpenseFilter(min_pence=1000, max_pence=2500), [1, 2]),
        (ExpenseFilter(merchant="sains"), [2]),
        (ExpenseFilter(merchant="100%_"), [4]),  # LIKE wildcards are escaped
        (ExpenseFilter(merchant="no such shop"), []),
    ],
)
def test_search_filters(repo, flt, expected_ids):
    assert [e.id for e in repo.search(flt).items] == expected_ids


def test_search_pagination_and_ordering(repo):
    page = repo.search(page=2, page_size=3)
    assert (page.total, page.pages, [e.id for e in page.items]) == (4, 2, [4])
    by_amount = repo.search(order="amount")
    assert [e.amount_pence for e in by_amount.items] == [9900, 2500, 1000, 700]
    with pytest.raises(ValidationError):
        repo.search(order="amount; DROP TABLE expenses")
    with pytest.raises(ValidationError):
        repo.search(page=0)


def test_aggregations_in_sql(repo):
    assert repo.totals_by_category(ExpenseFilter(month="2026-11")) == {
        "shopping": 9900,
        "food": 2500,
        "transport": 700,
    }
    assert repo.totals_by_month() == {"2026-10": 1000, "2026-11": 13100}
    top = repo.top_merchants(limit=2)
    assert [(m.merchant, m.total_pence) for m in top] == [
        ("100%_Deals", 9900),
        ("Sainsburys", 2500),
    ]


def test_merchant_history_picks_most_frequent_category(conn):
    repo = ExpenseRepository(conn)
    for cat in ("food", "food", "shopping"):
        repo.add(make_expense(500, cat, merchant="Tesco"))
    assert repo.merchant_category_history() == {"Tesco": "food"}


def test_add_many_skips_duplicate_hashes(conn):
    repo = ExpenseRepository(conn)
    batch = [make_expense(500, import_hash="a"), make_expense(600, import_hash="b")]
    assert repo.add_many(batch) == 2
    assert repo.add_many([*batch, make_expense(700, import_hash="c")]) == 1
    assert repo.count() == 3


def test_budget_upsert_and_rollover(conn):
    budgets = BudgetRepository(conn)
    budgets.set(Budget("2026-10", "food", 30000))
    budgets.set(Budget("2026-10", "food", 35000))
    budgets.set(Budget("2026-10", "health", 5000))
    budgets.set(Budget("2026-11", "health", 8000))
    assert budgets.copy_month("2026-10", "2026-11") == 1  # existing November budget kept
    assert budgets.for_month("2026-11") == {"food": 35000, "health": 8000}
