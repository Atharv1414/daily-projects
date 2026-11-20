from datetime import date

import pytest

from expense_tracker.errors import ValidationError
from expense_tracker.models import (
    CategoryRule,
    Expense,
    RecurringRule,
    add_months,
    month_bounds,
    parse_category,
    parse_date,
    parse_month,
)


@pytest.mark.parametrize("text", ["2026-11-03", "03/11/2026", "03-11-2026", "3 Nov 2026"])
def test_parse_date_accepts_uk_formats(text):
    assert parse_date(text) == date(2026, 11, 3)


@pytest.mark.parametrize("bad", ["31/02/2025", "2026-13-01", "yesterday", ""])
def test_parse_date_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        parse_date(bad)


def test_parse_category_and_month():
    assert parse_category("  Food ") == "food"
    assert parse_month("2026-02") == "2026-02"
    for bad_month in ("2026-13", "26-01", "2026/01"):
        with pytest.raises(ValidationError):
            parse_month(bad_month)
    with pytest.raises(ValidationError, match="Unknown category"):
        parse_category("crypto")


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2026, 1, 31), 2, date(2026, 3, 31)),
        (date(2026, 11, 15), 3, date(2027, 2, 15)),
        (date(2026, 3, 31), -1, date(2026, 2, 28)),
    ],
)
def test_add_months_clamps_to_month_end(start, months, expected):
    assert add_months(start, months) == expected


def test_month_bounds_leap_year():
    assert month_bounds("2028-02") == (date(2028, 2, 1), date(2028, 2, 29))


def test_domain_objects_validate_themselves():
    with pytest.raises(ValidationError):
        Expense(0, "food", date(2026, 1, 1))
    with pytest.raises(ValidationError):
        Expense(100, "food", date(2026, 1, 1), source="magic")
    with pytest.raises(ValidationError, match="End date"):
        RecurringRule("Gym", 100, "health", "monthly", date(2026, 5, 1), end_date=date(2026, 1, 1))
    with pytest.raises(ValidationError, match="Invalid pattern"):
        CategoryRule("([unclosed", "food")
