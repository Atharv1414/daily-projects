"""Budget status, month-end forecasting, trends and anomaly detection (pure functions)."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from .models import Expense, add_months, month_bounds, month_of

# 0.6745 is the 75th percentile of the standard normal; it makes the modified z-score
# comparable to an ordinary z-score for normally distributed data (Iglewicz & Hoaglin).
_MAD_SCALE = 0.6745
_MEAN_AD_SCALE = 1.2533  # sqrt(pi/2): mean absolute deviation -> sigma for normal data


@dataclass(frozen=True)
class CategoryStatus:
    category: str
    spent: int
    budget: int | None
    projected: int

    @property
    def remaining(self) -> int | None:
        return None if self.budget is None else self.budget - self.spent

    @property
    def over_budget(self) -> bool:
        return self.budget is not None and self.spent > self.budget

    @property
    def projected_over(self) -> bool:
        return self.budget is not None and not self.over_budget and self.projected > self.budget

    @property
    def percent_used(self) -> float | None:
        return None if not self.budget else self.spent / self.budget * 100


def month_progress(month: str, today: date) -> float:
    """Fraction of ``month`` elapsed as of ``today`` (0 before it starts, 1 once it's over)."""
    first, last = month_bounds(month)
    if today < first:
        return 0.0
    if today >= last:
        return 1.0
    return today.day / last.day


def project_month_end(spent: int, progress: float) -> int:
    """Linear run-rate projection; with no elapsed time we can't extrapolate."""
    if progress <= 0 or progress >= 1:
        return spent
    return round(spent / progress)


def budget_status(
    totals: Mapping[str, int], budgets: Mapping[str, int], progress: float = 1.0
) -> list[CategoryStatus]:
    categories = sorted(set(totals) | set(budgets), key=lambda c: (-totals.get(c, 0), c))
    return [
        CategoryStatus(
            c,
            totals.get(c, 0),
            budgets.get(c),
            project_month_end(totals.get(c, 0), progress),
        )
        for c in categories
    ]


def budget_warnings(statuses: Iterable[CategoryStatus], fmt=str) -> list[str]:
    warnings = []
    for s in statuses:
        if s.over_budget:
            warnings.append(
                f"{s.category}: spent {fmt(s.spent)} of {fmt(s.budget)} "
                f"(over by {fmt(-s.remaining)})"
            )
        elif s.projected_over:
            warnings.append(
                f"{s.category}: on track to spend {fmt(s.projected)} "
                f"against a {fmt(s.budget)} budget"
            )
    return warnings


@dataclass(frozen=True)
class TrendPoint:
    month: str
    total: int
    change_pct: float | None
    rolling_avg: int


def month_range(first: str, last: str) -> list[str]:
    start, _ = month_bounds(first)
    end, _ = month_bounds(last)
    months = []
    while start <= end:
        months.append(month_of(start))
        start = add_months(start, 1)
    return months


def monthly_trend(month_totals: Mapping[str, int], window: int = 3) -> list[TrendPoint]:
    """Month-over-month change and trailing rolling average; gaps are filled with zero."""
    if not month_totals:
        return []
    months = month_range(min(month_totals), max(month_totals))
    totals = [month_totals.get(m, 0) for m in months]
    points = []
    for i, (month, total) in enumerate(zip(months, totals, strict=True)):
        prev = totals[i - 1] if i else None
        change = None if not prev else (total - prev) / prev * 100
        trailing = totals[max(0, i - window + 1) : i + 1]
        points.append(TrendPoint(month, total, change, round(sum(trailing) / len(trailing))))
    return points


@dataclass(frozen=True)
class Anomaly:
    expense: Expense
    score: float
    median: int
    baseline: str  # "merchant" or "category": which history the expense was compared with


def _robust_sigma(values: list[float], median: float) -> float:
    mad = statistics.median(abs(v - median) for v in values)
    if mad:
        return mad / _MAD_SCALE
    # More than half the values are identical (e.g. a fixed subscription), so MAD is zero.
    # Fall back to the mean absolute deviation, scaled to estimate sigma.
    return statistics.fmean(abs(v - median) for v in values) * _MEAN_AD_SCALE


def detect_anomalies(
    expenses: Iterable[Expense], threshold: float = 3.5, min_history: int = 8
) -> list[Anomaly]:
    """Flag unusually large expenses using a robust modified z-score on log amounts.

    * **Like with like.** An expense is compared with its *merchant's* history when that
      merchant has at least ``min_history`` expenses, otherwise with its whole *category*.
      A £46 train ticket is normal for Trainline but extreme next to £7 TfL fares.
    * **Log scale.** Spending is multiplicative and right-skewed (most purchases are small,
      a few are large), so deviations are measured on ``log(amount)``. "Three times the
      usual" then means the same thing for a coffee and for a weekly shop.
    * **Median/MAD, not mean/std.** One huge purchase inflates the standard deviation enough
      to hide itself; median-based statistics are robust to exactly the outliers we want.

    Reference groups smaller than ``min_history`` are skipped as too noisy.
    """
    items = list(expenses)
    by_merchant: dict[str, list[Expense]] = defaultdict(list)
    by_category: dict[str, list[Expense]] = defaultdict(list)
    for e in items:
        by_category[e.category].append(e)
        if e.merchant:
            by_merchant[e.merchant].append(e)

    cache: dict[tuple[str, str], tuple[float, float] | None] = {}
    anomalies = []
    for e in items:
        merchant_history = by_merchant.get(e.merchant, [])
        if len(merchant_history) >= min_history:
            baseline, reference = "merchant", merchant_history
        else:
            baseline, reference = "category", by_category[e.category]
        if len(reference) < min_history:
            continue
        stats = _log_stats(baseline, e.merchant or e.category, reference, cache)
        if stats is None:
            continue
        median, sigma = stats
        score = (math.log(e.amount_pence) - median) / sigma
        if score > threshold:
            anomalies.append(Anomaly(e, round(score, 2), round(math.exp(median)), baseline))
    return sorted(anomalies, key=lambda a: a.score, reverse=True)


def _log_stats(
    baseline: str,
    key: str,
    reference: list[Expense],
    cache: dict[tuple[str, str], tuple[float, float] | None],
) -> tuple[float, float] | None:
    cache_key = (baseline, key if baseline == "merchant" else reference[0].category)
    if cache_key not in cache:
        logs = [math.log(r.amount_pence) for r in reference]
        median = statistics.median(logs)
        sigma = _robust_sigma(logs, median)
        cache[cache_key] = (median, sigma) if sigma else None
    return cache[cache_key]
