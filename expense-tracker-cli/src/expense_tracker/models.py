"""Domain models and input validation."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime

from .errors import ValidationError

CATEGORIES = (
    "food",
    "transport",
    "housing",
    "utilities",
    "entertainment",
    "health",
    "shopping",
    "other",
)
SOURCES = ("manual", "import", "recurring")
FREQUENCIES = ("weekly", "monthly", "yearly")

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y")


def parse_category(value: str) -> str:
    category = value.strip().lower()
    if category not in CATEGORIES:
        raise ValidationError(f"Unknown category {value!r}. Choose from: {', '.join(CATEGORIES)}")
    return category


def parse_month(value: str) -> str:
    """Validate a ``YYYY-MM`` month string."""
    try:
        datetime.strptime(value, "%Y-%m")
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"Month must be YYYY-MM, got {value!r}") from exc
    return value


def parse_date(value: str) -> date:
    """Parse ISO and common UK bank-statement date formats (day-first, never month-first)."""
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValidationError(f"Unrecognised date {value!r}")


def month_of(d: date) -> str:
    return d.strftime("%Y-%m")


def month_bounds(month: str) -> tuple[date, date]:
    year, mon = map(int, parse_month(month).split("-"))
    return date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])


def add_months(d: date, months: int) -> date:
    """Shift by whole months, clamping to the month's last day (31 Jan + 1 -> 28/29 Feb)."""
    index = d.year * 12 + (d.month - 1) + months
    year, mon = divmod(index, 12)
    mon += 1
    return date(year, mon, min(d.day, calendar.monthrange(year, mon)[1]))


@dataclass(frozen=True, slots=True)
class Expense:
    amount_pence: int
    category: str
    spent_on: date
    merchant: str = ""
    note: str = ""
    source: str = "manual"
    import_hash: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.amount_pence <= 0:
            raise ValidationError("Expense amount must be positive")
        if self.category not in CATEGORIES:
            raise ValidationError(f"Unknown category {self.category!r}")
        if self.source not in SOURCES:
            raise ValidationError(f"Unknown source {self.source!r}")

    @property
    def month(self) -> str:
        return month_of(self.spent_on)


@dataclass(frozen=True, slots=True)
class Budget:
    month: str
    category: str
    amount_pence: int

    def __post_init__(self) -> None:
        parse_month(self.month)
        if self.category not in CATEGORIES:
            raise ValidationError(f"Unknown category {self.category!r}")
        if self.amount_pence <= 0:
            raise ValidationError("Budget must be positive")


@dataclass(frozen=True, slots=True)
class RecurringRule:
    name: str
    amount_pence: int
    category: str
    frequency: str
    start_date: date
    merchant: str = ""
    end_date: date | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("Recurring rule needs a name")
        if self.amount_pence <= 0:
            raise ValidationError("Recurring amount must be positive")
        if self.category not in CATEGORIES:
            raise ValidationError(f"Unknown category {self.category!r}")
        if self.frequency not in FREQUENCIES:
            raise ValidationError(f"Frequency must be one of {', '.join(FREQUENCIES)}")
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError("End date is before start date")


@dataclass(frozen=True, slots=True)
class CategoryRule:
    """A user-defined regex that maps merchant names to a category."""

    pattern: str
    category: str
    priority: int = 100
    id: int | None = None

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValidationError(f"Unknown category {self.category!r}")
        try:
            re.compile(self.pattern)
        except re.error as exc:
            raise ValidationError(f"Invalid pattern {self.pattern!r}: {exc}") from exc
