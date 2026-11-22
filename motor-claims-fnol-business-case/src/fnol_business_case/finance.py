"""Financial model: 5-year cash flows, NPV/IRR/payback, sensitivity, scenarios and Monte Carlo.

Each assumption carries a low/base/high range, its source, and whether higher is better for
the case. The cash-flow function is vectorised with numpy, so the same code serves the
deterministic model and 10,000 Monte Carlo draws.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

YEARS = 5
RAMP = np.array([0.45, 0.80, 1.0, 1.0, 1.0])  # share of target adoption reached in year t


@dataclass(frozen=True)
class Assumption:
    name: str
    label: str
    base: float
    low: float
    high: float
    unit: str
    source: str
    higher_is_better: bool = True

    def __post_init__(self) -> None:
        if not self.low <= self.base <= self.high:
            raise ValueError(f"{self.name}: need low <= base <= high")


Assumptions = dict[str, Assumption]


def from_evidence(
    base: dict[str, float],
    did_per_digital: tuple[float, float, float],
    handle_saving: tuple[float, float, float],
    rental_slope: float,
) -> Assumptions:
    """Build the assumption set; data-backed values come from the analysis module.

    did_per_digital: (estimate, ci_low, ci_high) days saved per digital claim (negative).
    handle_saving: (estimate, ci_low, ci_high) minutes saved per digital FNOL (negative).
    """
    d, d_lo, d_hi = (-x for x in did_per_digital)
    h, h_lo, h_hi = (-x for x in handle_saving)
    items = [
        Assumption(
            "annual_claims",
            "Annual motor claims",
            base["annual_claims"],
            base["annual_claims"] * 0.9,
            base["annual_claims"] * 1.1,
            "claims",
            "Claims data, 12 months pre-pilot",
        ),
        Assumption(
            "claims_growth",
            "Claims volume growth p.a.",
            0.02,
            0.0,
            0.04,
            "%",
            "Planning assumption (book growth)",
        ),
        Assumption(
            "target_adoption",
            "Digital FNOL adoption (steady state)",
            0.55,
            0.38,
            0.70,
            "% of claims",
            "Pilot take-up 37% in first 4 months; benchmark 60-70%",
        ),
        Assumption(
            "handle_minutes_saved",
            "Handler minutes saved per digital FNOL",
            h,
            min(h_lo, h_hi),
            max(h_lo, h_hi),
            "min",
            "Pilot: digital vs phone handle time (Welch 95% CI)",
        ),
        Assumption(
            "handler_cost_per_hour",
            "Fully loaded handler cost",
            28.0,
            25.0,
            32.0,
            "£/hour",
            "£33k salary + 30% on-costs, 1,550 productive hours",
        ),
        Assumption(
            "handling_realisation",
            "Share of handling saving realised",
            0.7,
            0.5,
            0.9,
            "%",
            "Released via attrition and redeployment, not redundancies",
        ),
        Assumption(
            "cycle_days_saved",
            "Cycle days saved per digital claim",
            d,
            min(d_lo, d_hi),
            max(d_lo, d_hi),
            "days",
            "Pilot difference-in-differences / take-up (bootstrap 95% CI)",
        ),
        Assumption(
            "rental_days_per_cycle_day",
            "Hire days per cycle day",
            rental_slope,
            rental_slope * 0.85,
            rental_slope * 1.1,
            "days",
            "OLS of hire days on cycle days, claims with hire",
        ),
        Assumption(
            "rental_share",
            "Claims with a hire car",
            base["rental_share"],
            base["rental_share"] * 0.9,
            base["rental_share"] * 1.1,
            "%",
            "Claims data, 12 months pre-pilot",
        ),
        Assumption(
            "rental_cost_per_day",
            "Hire cost per day",
            base["rental_cost_per_day"],
            40.0,
            55.0,
            "£/day",
            "Claims data; credit-hire rates higher",
        ),
        Assumption(
            "mean_indemnity",
            "Average indemnity (excl. total loss)",
            base["mean_indemnity"],
            base["mean_indemnity"] * 0.9,
            base["mean_indemnity"] * 1.15,
            "£",
            "Claims data; claims inflation risk",
        ),
        Assumption(
            "leakage_reduction",
            "Indemnity leakage avoided (photo evidence at FNOL)",
            0.006,
            0.002,
            0.012,
            "% of indemnity",
            "Claims audit sample estimate; not measurable in the pilot yet",
        ),
        Assumption(
            "fraud_referral_rate",
            "Fraud referral rate",
            base["fraud_referral_rate"],
            base["fraud_referral_rate"] * 0.8,
            base["fraud_referral_rate"] * 1.2,
            "%",
            "Claims data",
        ),
        Assumption(
            "fraud_confirm_uplift",
            "Extra referrals confirmed (better evidence)",
            0.06,
            0.0,
            0.10,
            "pp",
            "Pilot directional only (small sample); counter-fraud team",
        ),
        Assumption(
            "fraud_value",
            "Average saving per confirmed fraud",
            6_500,
            4_500,
            9_000,
            "£",
            "Counter-fraud team",
        ),
        Assumption(
            "complaint_reduction",
            "Complaint rate reduction on digital claims",
            0.004,
            0.0,
            0.008,
            "pp",
            "Pilot NPS and complaint trend",
        ),
        Assumption(
            "cost_per_complaint",
            "Cost per complaint",
            600,
            400,
            900,
            "£",
            "Complaints MI incl. FOS case fees",
        ),
        Assumption(
            "capex",
            "Build and integration (year 0)",
            1_600_000,
            1_350_000,
            2_200_000,
            "£",
            "Vendor quotes + internal IT estimate, +15% contingency",
            False,
        ),
        Assumption(
            "change_cost",
            "Training and change (year 1)",
            250_000,
            180_000,
            350_000,
            "£",
            "Change team estimate",
            False,
        ),
        Assumption(
            "run_cost",
            "Run cost p.a. (licences, cloud, support)",
            380_000,
            320_000,
            480_000,
            "£/year",
            "Vendor quote + support model",
            False,
        ),
        Assumption(
            "discount_rate",
            "Discount rate",
            0.08,
            0.06,
            0.10,
            "%",
            "Group hurdle rate for change investments",
            False,
        ),
    ]
    return {a.name: a for a in items}


def values(assumptions: Assumptions, which: str = "base") -> dict[str, float]:
    return {k: getattr(a, which) for k, a in assumptions.items()}


Num = float | np.ndarray


def cash_flows(v: dict[str, Num]) -> dict[str, np.ndarray]:
    """Return arrays of shape (..., YEARS + 1) for each line of the model (year 0 = build)."""
    t = np.arange(1, YEARS + 1)
    shape = np.broadcast(*[np.asarray(x) for x in v.values()]).shape

    def col(x: Num) -> np.ndarray:
        return np.broadcast_to(np.asarray(x, dtype=float), shape).reshape(shape + (1,))

    claims = col(v["annual_claims"]) * (1 + col(v["claims_growth"])) ** t
    digital = claims * col(v["target_adoption"]) * RAMP
    handling = (
        digital
        * col(v["handle_minutes_saved"])
        / 60
        * col(v["handler_cost_per_hour"])
        * col(v["handling_realisation"])
    )
    rental = (
        digital
        * col(v["rental_share"])
        * col(v["cycle_days_saved"])
        * col(v["rental_days_per_cycle_day"])
        * col(v["rental_cost_per_day"])
    )
    leakage = digital * col(v["mean_indemnity"]) * col(v["leakage_reduction"])
    fraud = (
        digital
        * col(v["fraud_referral_rate"])
        * col(v["fraud_confirm_uplift"])
        * col(v["fraud_value"])
    )
    complaints = digital * col(v["complaint_reduction"]) * col(v["cost_per_complaint"])
    run = col(v["run_cost"]) * np.ones(YEARS)
    change = np.zeros(shape + (YEARS,))
    change[..., 0] = np.asarray(v["change_cost"], dtype=float)

    def with_y0(arr: np.ndarray, y0: Num = 0.0) -> np.ndarray:
        first = np.broadcast_to(np.asarray(y0, dtype=float), shape)[..., None]
        return np.concatenate([first, arr], axis=-1)

    lines = {
        "handling": with_y0(handling),
        "hire_car": with_y0(rental),
        "leakage": with_y0(leakage),
        "fraud": with_y0(fraud),
        "complaints": with_y0(complaints),
        "capex": with_y0(np.zeros(shape + (YEARS,)), -np.asarray(v["capex"], dtype=float)),
        "change": with_y0(-change),
        "run": with_y0(-run),
    }
    benefits = sum(lines[k] for k in ("handling", "hire_car", "leakage", "fraud", "complaints"))
    costs = lines["capex"] + lines["change"] + lines["run"]
    lines["benefits"] = benefits
    lines["costs"] = costs
    lines["net"] = benefits + costs
    return lines


def npv(rate: Num, flows: np.ndarray) -> np.ndarray | float:
    t = np.arange(flows.shape[-1])
    disc = (1 + np.asarray(rate, dtype=float)[..., None]) ** t
    out = (flows / disc).sum(axis=-1)
    return float(out) if np.ndim(out) == 0 else out


def irr(flows: np.ndarray, lo: float = -0.99, hi: float = 10.0, tol: float = 1e-7) -> float:
    """IRR by bisection. Requires a sign change (conventional investment profile)."""
    f = lambda r: float(npv(r, flows))  # noqa: E731
    if f(lo) * f(hi) > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def payback_years(flows: np.ndarray, rate: float | None = None) -> float:
    """Years until cumulative (optionally discounted) cash turns positive, interpolated."""
    f = flows.astype(float)
    if rate is not None:
        f = f / (1 + rate) ** np.arange(f.size)
    cum = np.cumsum(f)
    for i in range(1, cum.size):
        if cum[i] >= 0 > cum[i - 1]:
            return i - 1 + (-cum[i - 1]) / f[i]
    return 0.0 if cum[0] >= 0 else float("inf")


@dataclass(frozen=True)
class Metrics:
    npv: float
    irr: float
    payback: float
    discounted_payback: float
    roi: float
    total_benefits: float
    total_costs: float


def evaluate(v: dict[str, float]) -> Metrics:
    lines = cash_flows(v)
    net = lines["net"]
    rate = v["discount_rate"]
    costs = -lines["costs"].sum()
    return Metrics(
        float(npv(rate, net)),
        irr(net),
        payback_years(net),
        payback_years(net, rate),
        float(net.sum() / costs),
        float(lines["benefits"].sum()),
        float(costs),
    )


def cash_flow_table(v: dict[str, float]) -> pd.DataFrame:
    lines = cash_flows(v)
    order = [
        "handling",
        "hire_car",
        "leakage",
        "fraud",
        "complaints",
        "benefits",
        "capex",
        "change",
        "run",
        "costs",
        "net",
    ]
    df = pd.DataFrame({k: lines[k] for k in order}, index=[f"Y{i}" for i in range(YEARS + 1)]).T
    df["Total"] = df.sum(axis=1)
    disc = (1 + v["discount_rate"]) ** np.arange(YEARS + 1)
    df.loc["discounted net"] = list(lines["net"] / disc) + [float((lines["net"] / disc).sum())]
    df.loc["cumulative net"] = list(np.cumsum(lines["net"])) + [float("nan")]
    return df


def tornado(assumptions: Assumptions) -> pd.DataFrame:
    """One-at-a-time sensitivity: NPV with each assumption at its low and high value."""
    base_v = values(assumptions)
    base_npv = evaluate(base_v).npv
    rows = []
    for name, a in assumptions.items():
        lo = evaluate({**base_v, name: a.low}).npv
        hi = evaluate({**base_v, name: a.high}).npv
        rows.append(
            {
                "assumption": a.label,
                "name": name,
                "npv_low": lo,
                "npv_high": hi,
                "swing": abs(hi - lo),
                "base_npv": base_npv,
            }
        )
    return pd.DataFrame(rows).sort_values("swing", ascending=False).reset_index(drop=True)


def scenarios(assumptions: Assumptions) -> pd.DataFrame:
    """Pessimistic = every assumption at its unfavourable end; optimistic = favourable end."""

    def pick(favourable: bool) -> dict[str, float]:
        return {
            k: (a.high if a.higher_is_better == favourable else a.low)
            for k, a in assumptions.items()
        }

    rows = {}
    for label, v in (
        ("Pessimistic", pick(False)),
        ("Base", values(assumptions)),
        ("Optimistic", pick(True)),
    ):
        m = evaluate(v)
        rows[label] = {
            "NPV": m.npv,
            "IRR": m.irr,
            "Payback (yrs)": m.payback,
            "Discounted payback (yrs)": m.discounted_payback,
            "ROI": m.roi,
        }
    return pd.DataFrame(rows).T


@dataclass(frozen=True)
class MonteCarlo:
    npvs: np.ndarray
    p_positive: float
    p10: float
    p50: float
    p90: float
    mean: float


def monte_carlo(assumptions: Assumptions, n: int = 10_000, seed: int = 42) -> MonteCarlo:
    """Triangular(low, base, high) draws for every assumption, independent (a simplification)."""
    rng = np.random.default_rng(seed)
    draws = {}
    for k, a in assumptions.items():
        draws[k] = a.base if a.low == a.high else rng.triangular(a.low, a.base, a.high, n)
    lines = cash_flows(draws)
    vals = np.asarray(npv(draws["discount_rate"], lines["net"]))
    p10, p50, p90 = np.percentile(vals, [10, 50, 90])
    return MonteCarlo(
        vals, float((vals > 0).mean()), float(p10), float(p50), float(p90), float(vals.mean())
    )


def break_even(
    assumptions: Assumptions,
    name: str,
    lo: float,
    hi: float,
    metric: Callable[[Metrics], float] = lambda m: m.npv,
) -> float:
    """Value of one assumption at which NPV = 0, holding the others at base (bisection)."""
    base_v = values(assumptions)
    f = lambda x: metric(evaluate({**base_v, name: x}))  # noqa: E731
    if f(lo) * f(hi) > 0:
        return float("nan")
    for _ in range(100):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def with_override(assumptions: Assumptions, **base_values: float) -> Assumptions:
    out = dict(assumptions)
    for k, v in base_values.items():
        a = out[k]
        out[k] = replace(a, base=v, low=min(a.low, v), high=max(a.high, v))
    return out
