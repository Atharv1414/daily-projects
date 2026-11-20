from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from expense_tracker.errors import ValidationError
from expense_tracker.money import MAX_PENCE, format_money, parse_money


@pytest.mark.parametrize(
    ("text", "pence"),
    [
        ("12.5", 1250),
        ("£1,234.56", 123456),
        ("  7 ", 700),
        ("12.345", 1235),  # half-up
        ("0.005", 1),
        ("+3.10", 310),
    ],
)
def test_parse_money_valid(text, pence):
    assert parse_money(text) == pence


@pytest.mark.parametrize(
    ("text", "pence"), [("-4.20", -420), ("(4.20)", -420), ("-£1,000", -100000)]
)
def test_parse_money_negative_formats(text, pence):
    assert parse_money(text, allow_negative=True) == pence


@pytest.mark.parametrize("bad", ["", "abc", "N/A", "nan", "inf", "1.2.3", "£"])
def test_parse_money_rejects_garbage(bad):
    with pytest.raises(ValidationError):
        parse_money(bad)


def test_parse_money_rejects_negative_zero_and_huge():
    with pytest.raises(ValidationError, match="greater than zero"):
        parse_money("-1")
    with pytest.raises(ValidationError, match="zero"):
        parse_money("0.00")
    with pytest.raises(ValidationError, match="implausibly"):
        parse_money(str(MAX_PENCE))


def test_format_money():
    assert format_money(123456) == "£1,234.56"
    assert format_money(-5) == "-£0.05"
    assert format_money(700, "$") == "$7.00"


@given(st.integers(min_value=1, max_value=MAX_PENCE))
def test_format_then_parse_round_trips(pence):
    assert parse_money(format_money(pence)) == pence


@given(st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2))
def test_parse_matches_decimal_maths(value):
    assert parse_money(str(value)) == int(value * 100)
