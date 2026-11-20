"""Aggregation, budget checks and export."""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import IO

from .models import Expense


@dataclass(frozen=True)
class CategoryStatus:
    category: str
    spent: Decimal
    budget: Decimal | None

    @property
    def remaining(self) -> Decimal | None:
        return None if self.budget is None else self.budget - self.spent

    @property
    def over_budget(self) -> bool:
        return self.budget is not None and self.spent > self.budget

    @property
    def percent_used(self) -> float | None:
        if not self.budget:
            return None
        return float(self.spent / self.budget * 100)


def totals_by_category(expenses: Iterable[Expense]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for e in expenses:
        totals[e.category] += e.amount
    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def budget_status(expenses: Iterable[Expense], budgets: dict[str, Decimal]) -> list[CategoryStatus]:
    totals = totals_by_category(expenses)
    categories = sorted(set(totals) | set(budgets))
    return [CategoryStatus(c, totals.get(c, Decimal("0.00")), budgets.get(c)) for c in categories]


def money(value: Decimal) -> str:
    """Format a Decimal as pounds with exactly two decimal places."""
    return f"£{value.quantize(Decimal('0.01')):,}"


def over_budget_warnings(statuses: Iterable[CategoryStatus]) -> list[str]:
    return [
        f"{s.category}: spent {money(s.spent)} of {money(s.budget)} budget "
        f"(over by {money(-s.remaining)})"
        for s in statuses
        if s.over_budget
    ]


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a simple aligned plain-text table."""
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row, strict=True)]
    line = "-+-".join("-" * w for w in widths)

    def fmt(cells: list[str]) -> str:
        return " | ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)).rstrip()

    out = [fmt(headers), line] + [fmt(r) for r in rows]
    return "\n".join(out)


def summary_table(statuses: list[CategoryStatus]) -> str:
    rows = []
    for s in statuses:
        budget = money(s.budget) if s.budget is not None else "-"
        used = f"{s.percent_used:.0f}%" if s.percent_used is not None else "-"
        flag = "OVER" if s.over_budget else ""
        rows.append([s.category, money(s.spent), budget, used, flag])
    total = sum((s.spent for s in statuses), Decimal("0.00"))
    rows.append(["TOTAL", money(total), "", "", ""])
    return render_table(["Category", "Spent", "Budget", "Used", ""], rows)


def export_csv(expenses: Iterable[Expense], fh: IO[str]) -> int:
    writer = csv.writer(fh)
    writer.writerow(["id", "date", "category", "amount", "note"])
    count = 0
    for e in expenses:
        writer.writerow([e.id, e.spent_on.isoformat(), e.category, str(e.amount), e.note])
        count += 1
    return count
