from datetime import date
from decimal import Decimal
from io import StringIO

import pytest

from expense_tracker.cli import run
from expense_tracker.models import (
    Expense,
    ValidationError,
    parse_amount,
    parse_category,
    parse_month,
)
from expense_tracker.reports import (
    budget_status,
    export_csv,
    over_budget_warnings,
    summary_table,
    totals_by_category,
)
from expense_tracker.storage import Store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def exp(amount, category, day="2026-11-05", note=""):
    return Expense(Decimal(amount), category, date.fromisoformat(day), note)


# --- models ---------------------------------------------------------------
def test_parse_amount_rounds_to_pennies():
    assert parse_amount("12.345") == Decimal("12.35")
    assert parse_amount("7") == Decimal("7.00")


@pytest.mark.parametrize("bad", ["0", "-5", "abc", ""])
def test_parse_amount_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        parse_amount(bad)


def test_parse_category_normalises_case():
    assert parse_category("  Food ") == "food"


def test_parse_category_rejects_unknown():
    with pytest.raises(ValidationError):
        parse_category("crypto")


def test_parse_month():
    assert parse_month("2026-11") == "2026-11"
    with pytest.raises(ValidationError):
        parse_month("2026-13")


# --- storage --------------------------------------------------------------
def test_add_and_list_assigns_ids(store):
    a = store.add_expense(exp("10", "food"))
    b = store.add_expense(exp("5", "transport"))
    assert (a.id, b.id) == (1, 2)
    assert [e.amount for e in store.list_expenses()] == [Decimal("10"), Decimal("5")]


def test_list_filters_by_month_and_category(store):
    store.add_expense(exp("10", "food", "2026-10-30"))
    store.add_expense(exp("20", "food", "2026-11-01"))
    store.add_expense(exp("30", "health", "2026-11-02"))
    assert len(store.list_expenses(month="2026-11")) == 2
    assert len(store.list_expenses(month="2026-11", category="food")) == 1


def test_delete_expense(store):
    e = store.add_expense(exp("10", "food"))
    assert store.delete_expense(e.id) is True
    assert store.delete_expense(e.id) is False


def test_budget_upsert(store):
    store.set_budget("2026-11", "food", Decimal("100"))
    store.set_budget("2026-11", "food", Decimal("150"))
    assert store.get_budgets("2026-11") == {"food": Decimal("150")}


# --- reports --------------------------------------------------------------
def test_totals_sorted_descending():
    totals = totals_by_category([exp("5", "food"), exp("20", "health"), exp("6", "food")])
    assert list(totals.items()) == [("health", Decimal("20")), ("food", Decimal("11"))]


def test_budget_status_flags_overspend():
    statuses = budget_status(
        [exp("120", "food")], {"food": Decimal("100"), "health": Decimal("50")}
    )
    by_cat = {s.category: s for s in statuses}
    assert by_cat["food"].over_budget and by_cat["food"].remaining == Decimal("-20")
    assert by_cat["health"].spent == Decimal("0") and not by_cat["health"].over_budget


def test_over_budget_warning_text():
    warnings = over_budget_warnings(budget_status([exp("120", "food")], {"food": Decimal("100")}))
    assert warnings == ["food: spent £120.00 of £100.00 budget (over by £20.00)"]


def test_summary_table_includes_total():
    table = summary_table(budget_status([exp("10", "food"), exp("5", "other")], {}))
    assert "TOTAL" in table and "£15.00" in table


def test_export_csv():
    buf = StringIO()
    n = export_csv([exp("9.99", "food", note="lunch")], buf)
    assert n == 1
    assert buf.getvalue().splitlines()[1] == ",2026-11-05,food,9.99,lunch"


# --- CLI ------------------------------------------------------------------
def test_cli_add_and_list(store, capsys):
    assert run(["add", "12.50", "food", "-n", "Lunch", "-d", "2026-11-03"], store) == 0
    assert run(["list", "-m", "2026-11"], store) == 0
    out = capsys.readouterr().out
    assert "Added #1" in out and "Lunch" in out


def test_cli_warns_when_over_budget(store, capsys):
    run(["budget", "food", "20", "-m", "2026-11"], store)
    run(["add", "25", "food", "-d", "2026-11-03"], store)
    assert "Over budget" in capsys.readouterr().out


def test_cli_invalid_category_returns_error(store, capsys):
    assert run(["add", "5", "spaceships"], store) == 2
    assert "Unknown category" in capsys.readouterr().err


def test_cli_invalid_date_returns_error(store, capsys):
    assert run(["add", "5", "food", "-d", "yesterday"], store) == 2


def test_cli_summary_and_export(store, tmp_path, capsys):
    run(["add", "40", "health", "-d", "2026-11-03"], store)
    assert run(["summary", "-m", "2026-11"], store) == 0
    out_file = tmp_path / "out.csv"
    assert run(["export", str(out_file)], store) == 0
    assert "health" in out_file.read_text()
    assert "Summary for 2026-11" in capsys.readouterr().out


def test_cli_delete_missing(store):
    assert run(["delete", "99"], store) == 1
