"""Domain models for the expense tracker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

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


class ValidationError(ValueError):
    """Raised when user input fails validation."""


def parse_amount(value: str | float | Decimal) -> Decimal:
    """Parse a positive monetary amount, rounded to 2 decimal places."""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"Invalid amount: {value!r}") from exc
    if amount <= 0:
        raise ValidationError("Amount must be greater than zero")
    return amount


def parse_category(value: str) -> str:
    category = value.strip().lower()
    if category not in CATEGORIES:
        raise ValidationError(f"Unknown category {value!r}. Choose from: {', '.join(CATEGORIES)}")
    return category


def parse_month(value: str) -> str:
    """Validate a YYYY-MM month string."""
    try:
        date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise ValidationError(f"Month must be YYYY-MM, got {value!r}") from exc
    return value


@dataclass(frozen=True)
class Expense:
    amount: Decimal
    category: str
    spent_on: date
    note: str = ""
    id: int | None = None

    @property
    def month(self) -> str:
        return self.spent_on.strftime("%Y-%m")
