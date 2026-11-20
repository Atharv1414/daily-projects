"""Application service: the use cases, orchestrating repositories and pure analytics.

The CLI (and any future API or UI) talks only to ``ExpenseTracker``; it never touches SQL.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .analytics import (
    Anomaly,
    CategoryStatus,
    TrendPoint,
    budget_status,
    budget_warnings,
    detect_anomalies,
    month_progress,
    monthly_trend,
)
from .categorizer import Categorizer, normalise_merchant
from .config import Settings
from .db import open_database
from .errors import ImportFormatError, ValidationError
from .importer import ImportResult, StatementImporter
from .models import Budget, CategoryRule, Expense, RecurringRule, add_months, month_bounds
from .money import format_money
from .recurring import RecurringService
from .repository import (
    BudgetRepository,
    CategoryRuleRepository,
    ExpenseFilter,
    ExpenseRepository,
    ImportRunRepository,
    MerchantStat,
    RecurringRuleRepository,
)


@dataclass(frozen=True)
class AddResult:
    expense: Expense
    category_reason: str
    warnings: list[str]


class ExpenseTracker:
    def __init__(self, conn: sqlite3.Connection, settings: Settings | None = None) -> None:
        self.conn = conn
        self.settings = settings or Settings()
        self.expenses = ExpenseRepository(conn)
        self.budgets = BudgetRepository(conn)
        self.recurring_rules = RecurringRuleRepository(conn)
        self.category_rules = CategoryRuleRepository(conn)
        self.import_runs = ImportRunRepository(conn)

    @classmethod
    def open(cls, settings: Settings) -> ExpenseTracker:
        return cls(open_database(settings.db_path), settings)

    def close(self) -> None:
        self.conn.close()

    def money(self, pence: int) -> str:
        return format_money(pence, self.settings.currency_symbol)

    def categorizer(self) -> Categorizer:
        return Categorizer(self.category_rules.list(), self.expenses.merchant_category_history())

    # --- expenses ------------------------------------------------------------
    def add_expense(
        self,
        amount_pence: int,
        spent_on: date,
        category: str | None = None,
        merchant: str = "",
        note: str = "",
        today: date | None = None,
    ) -> AddResult:
        merchant = normalise_merchant(merchant) if merchant else ""
        if category is None:
            if not merchant:
                raise ValidationError("Give a category, or a merchant to auto-categorise from")
            decision = self.categorizer().categorize(merchant)
            category, reason = decision.category, decision.reason
        else:
            reason = "manual"
        expense = self.expenses.add(Expense(amount_pence, category, spent_on, merchant, note))
        statuses = self.summary(expense.month, today=today or date.today())
        warnings = budget_warnings(
            [s for s in statuses if s.category == expense.category], self.money
        )
        return AddResult(expense, reason, warnings)

    # --- budgets -------------------------------------------------------------
    def set_budget(self, month: str, category: str, amount_pence: int) -> None:
        self.budgets.set(Budget(month, category, amount_pence))

    def roll_budgets_forward(self, month: str) -> int:
        previous = add_months(month_bounds(month)[0], -1).strftime("%Y-%m")
        return self.budgets.copy_month(previous, month)

    # --- import / recurring / rules -----------------------------------------
    def import_statement(self, path: Path, quarantine: Path | None = None) -> ImportResult:
        if not path.is_file():
            raise ImportFormatError(f"Statement file not found: {path}")
        importer = StatementImporter(self.expenses, self.import_runs, self.categorizer())
        return importer.import_file(path, quarantine)

    def add_recurring(self, rule: RecurringRule) -> RecurringRule:
        return self.recurring_rules.add(rule)

    def materialise_recurring(self, until: date) -> int:
        return RecurringService(self.recurring_rules, self.expenses).materialise(until)

    def add_category_rule(self, pattern: str, category: str, priority: int = 100) -> CategoryRule:
        return self.category_rules.add(CategoryRule(pattern, category, priority))

    # --- reporting -------------------------------------------------------------
    def summary(self, month: str, today: date) -> list[CategoryStatus]:
        totals = self.expenses.totals_by_category(ExpenseFilter(month=month))
        return budget_status(totals, self.budgets.for_month(month), month_progress(month, today))

    def warnings(self, statuses: list[CategoryStatus]) -> list[str]:
        return budget_warnings(statuses, self.money)

    def trend(self, months: int, end_month: str) -> list[TrendPoint]:
        end_first, end_last = month_bounds(end_month)
        start = add_months(end_first, -(months - 1))
        totals = self.expenses.totals_by_month(ExpenseFilter(start=start, end=end_last))
        totals.setdefault(start.strftime("%Y-%m"), 0)
        totals.setdefault(end_month, 0)
        return monthly_trend(totals)

    def anomalies(self, month: str | None = None) -> list[Anomaly]:
        found = detect_anomalies(self.expenses.iter(), self.settings.anomaly_threshold)
        return [a for a in found if month is None or a.expense.month == month]

    def top_merchants(self, month: str | None = None, limit: int = 10) -> list[MerchantStat]:
        return self.expenses.top_merchants(ExpenseFilter(month=month), limit)
