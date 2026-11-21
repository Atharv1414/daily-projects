"""Statistical tests with effect sizes and confidence intervals.

Formulas are written out (rather than only calling a library) so each number in the report
can be traced; the tests cross-check them against statsmodels/scipy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats


def wilson_ci(successes: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score interval: well-behaved for small n and rates near 0 or 1."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= successes <= n:
        raise ValueError("successes must be between 0 and n")
    z = stats.norm.ppf(1 - alpha / 2)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class TwoProportionResult:
    control_rate: float
    treatment_rate: float
    n_control: int
    n_treatment: int
    diff: float  # treatment - control (absolute, percentage points as a fraction)
    diff_ci: tuple[float, float]
    z: float
    p_value: float
    relative_risk: float
    rr_ci: tuple[float, float]
    cohens_h: float
    nnt: float  # reminders needed to prevent one DNA (inf if no benefit)

    @property
    def relative_reduction(self) -> float:
        return 1 - self.relative_risk

    @property
    def significant(self) -> bool:
        return self.p_value < 0.05


def two_proportion_test(
    x_c: int, n_c: int, x_t: int, n_t: int, alpha: float = 0.05
) -> TwoProportionResult:
    """Two-sided z-test (pooled SE) with an unpooled Wald CI for the difference."""
    if min(n_c, n_t) <= 0:
        raise ValueError("both groups need observations")
    p_c, p_t = x_c / n_c, x_t / n_t
    pooled = (x_c + x_t) / (n_c + n_t)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / n_c + 1 / n_t))
    z = (p_t - p_c) / se_pooled if se_pooled > 0 else 0.0
    p_value = 2 * stats.norm.sf(abs(z))
    zc = stats.norm.ppf(1 - alpha / 2)
    se = math.sqrt(p_c * (1 - p_c) / n_c + p_t * (1 - p_t) / n_t)
    diff = p_t - p_c
    if x_c > 0 and x_t > 0:
        rr = p_t / p_c
        se_log = math.sqrt(1 / x_t - 1 / n_t + 1 / x_c - 1 / n_c)
        rr_ci = (rr * math.exp(-zc * se_log), rr * math.exp(zc * se_log))
    else:
        rr, rr_ci = float("nan"), (float("nan"), float("nan"))
    h = 2 * math.asin(math.sqrt(p_t)) - 2 * math.asin(math.sqrt(p_c))
    nnt = 1 / -diff if diff < 0 else float("inf")
    return TwoProportionResult(
        p_c, p_t, n_c, n_t, diff, (diff - zc * se, diff + zc * se), z, p_value, rr, rr_ci, h, nnt
    )


def srm_check(n_a: int, n_b: int, expected_ratio: float = 0.5) -> float:
    """Sample-ratio-mismatch p-value. A tiny value means randomisation is broken."""
    total = n_a + n_b
    expected = [total * expected_ratio, total * (1 - expected_ratio)]
    return float(stats.chisquare([n_a, n_b], expected).pvalue)


def power_two_proportions(p1: float, p2: float, n_per_arm: int, alpha: float = 0.05) -> float:
    """Approximate power of a two-sided two-proportion z-test."""
    h = abs(2 * math.asin(math.sqrt(p2)) - 2 * math.asin(math.sqrt(p1)))
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    return float(stats.norm.cdf(h * math.sqrt(n_per_arm / 2) - z_alpha))


def required_n_per_arm(p1: float, p2: float, power: float = 0.8, alpha: float = 0.05) -> int:
    h = abs(2 * math.asin(math.sqrt(p2)) - 2 * math.asin(math.sqrt(p1)))
    if h == 0:
        raise ValueError("no effect to detect")
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return math.ceil(2 * (z / h) ** 2)


@dataclass(frozen=True)
class ChiSquareResult:
    chi2: float
    dof: int
    p_value: float
    cramers_v: float


def chi_square(table: np.ndarray) -> ChiSquareResult:
    """Chi-square test of independence with Cramér's V as the effect size."""
    chi2, p, dof, _ = stats.chi2_contingency(table, correction=False)
    n = table.sum()
    k = min(table.shape) - 1
    return ChiSquareResult(float(chi2), int(dof), float(p), math.sqrt(chi2 / (n * k)))
