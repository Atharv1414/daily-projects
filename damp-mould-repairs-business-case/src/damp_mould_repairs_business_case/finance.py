"""Five-year financial case built from simulated operational results."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

YEARS = 5


@dataclass(frozen=True)
class Assumptions:
    """Illustrative planning figures in real 2026 pounds, to be confirmed by Finance."""

    discount_rate: float = 0.035  # HM Treasury Green Book
    claim_rate: float = 0.04  # breached cases that become a disrepair claim
    claim_cost: float = 7_500.0  # compensation, legal fees and officer time
    goodwill: float = 110.0  # complaint handling and goodwill per breached case
    implementation: float = 185_000.0
    change_and_training: float = 45_000.0
    optimism_bias: float = 0.20  # uplift on one-off costs
    annual_licences: float = 58_000.0
    annual_support: float = 22_000.0
    surveyor_cost: float = 52_000.0
    crew_cost: float = 98_000.0
    admin_cost: float = 33_000.0
    year_one_effect: float = 0.5

    @property
    def breach_cost(self) -> float:
        return self.claim_rate * self.claim_cost + self.goodwill


@dataclass(frozen=True)
class Option:
    """What an option needs and what it changes, per year against doing nothing."""

    name: str
    breaches_avoided: float
    extra_surveyors: int = 0
    extra_crews: int = 0
    extra_admin: int = 0
    digital: bool = False
    queue_only: bool = False


def cash_flows(option: Option, a: Assumptions) -> list[float]:
    one_off = 0.0
    if option.digital:
        one_off = a.implementation + a.change_and_training
    elif option.queue_only:
        one_off = 0.15 * a.implementation + 0.4 * a.change_and_training
    running = (
        option.extra_surveyors * a.surveyor_cost
        + option.extra_crews * a.crew_cost
        + option.extra_admin * a.admin_cost
    )
    if option.digital:
        running += a.annual_licences + a.annual_support
    benefit = option.breaches_avoided * a.breach_cost
    flows = [-one_off * (1 + a.optimism_bias)]
    for year in range(1, YEARS + 1):
        flows.append(benefit * (a.year_one_effect if year == 1 else 1.0) - running)
    return flows


def npv(flows: list[float], rate: float) -> float:
    return sum(f / (1 + rate) ** t for t, f in enumerate(flows))


def irr(flows: list[float]) -> float | None:
    """Bisection. None when there is no sign change, so no single rate exists."""
    low, high = -0.99, 100.0
    if flows[0] >= 0 or npv(flows, low) * npv(flows, high) > 0:
        return None
    for _ in range(200):
        middle = (low + high) / 2
        if npv(flows, middle) > 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def payback_years(flows: list[float]) -> float | None:
    """Undiscounted, interpolated within the year. None if never recovered."""
    if flows[0] >= 0:
        return None
    total = flows[0]
    for year, flow in enumerate(flows[1:], start=1):
        if total + flow >= 0 and flow > 0:
            return year - 1 + -total / flow
        total += flow
    return None


def option_npv(option: Option, a: Assumptions) -> float:
    return npv(cash_flows(option, a), a.discount_rate)


def break_even_breach_cost(option: Option, a: Assumptions) -> float | None:
    """Cost per breached case at which the option's NPV is zero (NPV is linear in it)."""
    without = option_npv(replace(option, breaches_avoided=0.0), a)
    gain = option_npv(option, a) - without
    return None if gain <= 0 else -without / gain * a.breach_cost


@dataclass(frozen=True)
class Swing:
    assumption: str
    low: float
    high: float

    @property
    def width(self) -> float:
        return abs(self.high - self.low)


def tornado(option: Option, a: Assumptions, spread: float = 0.30) -> list[Swing]:
    """NPV with each assumption moved by ±spread on its own, widest first."""
    swings = []
    for f in fields(a):
        value = getattr(a, f.name)
        low = option_npv(option, replace(a, **{f.name: value * (1 - spread)}))
        high = option_npv(option, replace(a, **{f.name: value * (1 + spread)}))
        swings.append(Swing(f.name, low, high))
    few = replace(option, breaches_avoided=option.breaches_avoided * (1 - spread))
    many = replace(option, breaches_avoided=option.breaches_avoided * (1 + spread))
    swings.append(Swing("breaches_avoided", option_npv(few, a), option_npv(many, a)))
    return sorted((s for s in swings if s.width > 0), key=lambda s: -s.width)
