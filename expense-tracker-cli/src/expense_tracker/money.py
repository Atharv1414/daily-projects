"""Money parsing and formatting.

Amounts are stored as integer pence everywhere inside the system. Integers make sums exact,
keep SQLite aggregation (``SUM``) correct, and avoid ever mixing floats into money maths.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .errors import ValidationError

MAX_PENCE = 10_000_000_00  # £10m: anything larger is almost certainly a data error
_STRIP = str.maketrans("", "", "£$€, ")


def parse_money(
    value: str | int | Decimal, *, allow_negative: bool = False, allow_zero: bool = False
) -> int:
    """Parse a human or bank-statement amount into integer pence.

    Accepts ``"12.5"``, ``"£1,234.56"``, ``"-4.20"`` and accounting negatives ``"(4.20)"``.
    Rounds half-up to the nearest penny.
    """
    if isinstance(value, bool):
        raise ValidationError(f"Invalid amount: {value!r}")
    if isinstance(value, int | Decimal):
        dec = Decimal(value)
    else:
        text = str(value).strip()
        negative = False
        if text.startswith("(") and text.endswith(")"):
            negative, text = True, text[1:-1]
        text = text.translate(_STRIP)
        if text.startswith("-"):
            negative, text = not negative, text[1:]
        elif text.startswith("+"):
            text = text[1:]
        if not text:
            raise ValidationError(f"Invalid amount: {value!r}")
        try:
            dec = Decimal(text)
        except InvalidOperation as exc:
            raise ValidationError(f"Invalid amount: {value!r}") from exc
        if negative:
            dec = -dec
    if not dec.is_finite():
        raise ValidationError(f"Invalid amount: {value!r}")
    pence = int((dec * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if pence < 0 and not allow_negative:
        raise ValidationError("Amount must be greater than zero")
    if pence == 0 and not allow_zero:
        raise ValidationError("Amount must not be zero")
    if abs(pence) > MAX_PENCE:
        raise ValidationError(f"Amount {value!r} is implausibly large")
    return pence


def format_money(pence: int, symbol: str = "£") -> str:
    """Format pence as e.g. ``£1,234.50`` or ``-£4.20``."""
    sign = "-" if pence < 0 else ""
    p = abs(pence)
    return f"{sign}{symbol}{p // 100:,}.{p % 100:02d}"
