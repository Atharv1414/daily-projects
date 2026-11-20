"""Recurring expenses (rent, subscriptions, gym...) materialised into real expense rows.

Occurrences are always computed from the rule's start date (``start + n months``) rather
than from the previous occurrence, so a rule starting on the 31st returns to the 31st after
passing through February instead of drifting to the 28th forever.

Materialising is idempotent: each occurrence has the stable key
``recurring:<rule id>:<date>`` stored in ``import_hash``, so running it daily from cron is
safe.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

from .models import Expense, RecurringRule, add_months
from .repository import ExpenseRepository, RecurringRuleRepository


def nth_occurrence(rule: RecurringRule, n: int) -> date:
    if rule.frequency == "weekly":
        return rule.start_date + timedelta(weeks=n)
    if rule.frequency == "monthly":
        return add_months(rule.start_date, n)
    return add_months(rule.start_date, 12 * n)


def occurrences(rule: RecurringRule, until: date) -> Iterator[date]:
    """Yield every occurrence from the start date up to and including ``until``."""
    last = min(until, rule.end_date) if rule.end_date else until
    n = 0
    while (when := nth_occurrence(rule, n)) <= last:
        yield when
        n += 1


class RecurringService:
    def __init__(self, rules: RecurringRuleRepository, expenses: ExpenseRepository) -> None:
        self.rules = rules
        self.expenses = expenses

    def materialise(self, until: date) -> int:
        """Create any missing expense rows up to ``until``; returns how many were created."""

        def pending() -> Iterator[Expense]:
            for rule in self.rules.list():
                for when in occurrences(rule, until):
                    yield Expense(
                        amount_pence=rule.amount_pence,
                        category=rule.category,
                        spent_on=when,
                        merchant=rule.merchant or rule.name,
                        note=f"recurring: {rule.name}",
                        source="recurring",
                        import_hash=f"recurring:{rule.id}:{when.isoformat()}",
                    )

        return self.expenses.add_many(pending())
