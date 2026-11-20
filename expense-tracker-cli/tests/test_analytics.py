import random
from datetime import date, timedelta

import pytest

from expense_tracker.analytics import (
    budget_status,
    budget_warnings,
    detect_anomalies,
    month_progress,
    monthly_trend,
    project_month_end,
)
from expense_tracker.models import Expense


@pytest.mark.parametrize(
    ("today", "expected"),
    [(date(2026, 10, 31), 0.0), (date(2026, 11, 15), 0.5), (date(2026, 12, 1), 1.0)],
)
def test_month_progress(today, expected):
    assert month_progress("2026-11", today) == expected


def test_projection_and_budget_flags():
    assert project_month_end(15000, 0.5) == 30000
    assert project_month_end(15000, 0.0) == 15000
    statuses = budget_status(
        {"food": 30000, "transport": 6000}, {"food": 25000, "transport": 10000}, progress=0.5
    )
    food, transport = statuses
    assert food.over_budget and not food.projected_over
    assert transport.projected == 12000 and transport.projected_over
    assert len(budget_warnings(statuses)) == 2


def test_budget_status_includes_unspent_budgets():
    (status,) = budget_status({}, {"health": 5000})
    assert (status.spent, status.remaining, status.percent_used) == (0, 5000, 0.0)


def test_monthly_trend_fills_gaps_and_computes_changes():
    points = monthly_trend({"2026-08": 10000, "2026-10": 20000, "2026-11": 25000})
    assert [p.month for p in points] == ["2026-08", "2026-09", "2026-10", "2026-11"]
    assert points[1].total == 0 and points[2].change_pct is None  # no % change from zero
    assert points[3].change_pct == pytest.approx(25.0)
    assert points[3].rolling_avg == 15000


def _history(merchant, category, median_pounds, n, seed):
    rng = random.Random(seed)
    start = date(2026, 1, 1)
    return [
        Expense(
            round(rng.lognormvariate(0, 0.3) * median_pounds * 100),
            category,
            start + timedelta(days=i),
            merchant,
            id=seed * 1000 + i,
        )
        for i in range(n)
    ]


def test_anomalies_find_planted_spikes_with_few_false_positives():
    expenses = (
        _history("Tfl", "transport", 7, 200, 1)
        + _history("Trainline", "transport", 45, 30, 2)
        + _history("Tesco", "food", 25, 120, 3)
    )
    spike = Expense(31240, "transport", date(2026, 6, 1), "Trainline", id=1)
    normal_train = Expense(6500, "transport", date(2026, 6, 2), "Trainline", id=2)
    one_off = Expense(89900, "food", date(2026, 6, 3), "Fancy Restaurant", id=3)
    found = detect_anomalies([*expenses, spike, normal_train, one_off])
    flagged = {a.expense.id for a in found}
    assert {1, 3} <= flagged
    assert 2 not in flagged  # £65 is normal for Trainline even though TfL fares are £7
    assert len(flagged) <= 5
    by_id = {a.expense.id: a for a in found}
    assert by_id[1].baseline == "merchant" and by_id[3].baseline == "category"


def test_anomalies_handle_fixed_price_subscriptions():
    subs = [Expense(1099, "entertainment", date(2026, m, 14), "Netflix") for m in range(1, 13)]
    hike = Expense(1799, "entertainment", date(2026, 12, 20), "Netflix", id=99)
    assert [a.expense.id for a in detect_anomalies([*subs, hike])] == [99]
    assert detect_anomalies(subs) == []
    assert detect_anomalies(subs[:3]) == []  # not enough history
