from datetime import date

from expense_tracker.models import RecurringRule
from expense_tracker.recurring import RecurringService, occurrences
from expense_tracker.repository import ExpenseFilter, ExpenseRepository, RecurringRuleRepository


def test_monthly_rule_on_31st_does_not_drift():
    rule = RecurringRule("Rent", 145000, "housing", "monthly", date(2026, 1, 31))
    assert list(occurrences(rule, date(2026, 5, 1))) == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


def test_weekly_and_yearly_rules_respect_end_date():
    weekly = RecurringRule(
        "Cleaner", 4000, "housing", "weekly", date(2026, 11, 2), end_date=date(2026, 11, 20)
    )
    assert len(list(occurrences(weekly, date(2027, 1, 1)))) == 3
    yearly = RecurringRule("Prime", 9500, "shopping", "yearly", date(2024, 2, 29))
    assert list(occurrences(yearly, date(2026, 12, 31)))[1:] == [
        date(2025, 2, 28),
        date(2026, 2, 28),
    ]


def test_materialise_is_idempotent(conn):
    rules, expenses = RecurringRuleRepository(conn), ExpenseRepository(conn)
    rules.add(RecurringRule("Gym", 3299, "health", "monthly", date(2026, 9, 1), merchant="PureGym"))
    service = RecurringService(rules, expenses)
    assert service.materialise(date(2026, 11, 15)) == 3
    assert service.materialise(date(2026, 11, 15)) == 0
    assert service.materialise(date(2026, 12, 1)) == 1
    created = list(expenses.iter(ExpenseFilter(source="recurring")))
    assert {e.merchant for e in created} == {"PureGym"}
