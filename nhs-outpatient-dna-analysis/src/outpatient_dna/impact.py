"""Financial impact of DNAs and of the two interventions, in GBP with uncertainty ranges."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from outpatient_dna.config import COST_PER_CALL_GBP, COST_PER_DNA_GBP, COST_PER_SMS_GBP
from outpatient_dna.stats import TwoProportionResult

# Assumption, not measured here: a personal phone call cuts DNA risk by 30% among those
# reached, with 65% of calls answered. Flagged in the report as needing its own trial.
CALL_EFFECT = 0.30
CALL_CONTACT_RATE = 0.65


@dataclass(frozen=True)
class Scenario:
    name: str
    appointments_targeted: int
    dnas_avoided: float
    dnas_avoided_low: float
    dnas_avoided_high: float
    intervention_cost_gbp: float

    @property
    def gross_saving_gbp(self) -> float:
        return self.dnas_avoided * COST_PER_DNA_GBP

    @property
    def net_saving_gbp(self) -> float:
        return self.gross_saving_gbp - self.intervention_cost_gbp

    @property
    def net_range_gbp(self) -> tuple[float, float]:
        return (
            self.dnas_avoided_low * COST_PER_DNA_GBP - self.intervention_cost_gbp,
            self.dnas_avoided_high * COST_PER_DNA_GBP - self.intervention_cost_gbp,
        )

    @property
    def roi(self) -> float:
        cost = self.intervention_cost_gbp
        return self.net_saving_gbp / cost if cost else float("inf")


def baseline_cost(attendable: pd.DataFrame, year: int) -> dict[str, float]:
    y = attendable[attendable["appointment_datetime"].dt.year == year]
    dnas = int(y["dna"].sum())
    return {
        "year": year,
        "appointments": len(y),
        "dnas": dnas,
        "dna_rate": dnas / len(y),
        "cost_gbp": dnas * COST_PER_DNA_GBP,
    }


def sms_rollout(attendable: pd.DataFrame, trial: TwoProportionResult, year: int) -> Scenario:
    """Switch every SMS reminder to the cost message (no extra messages are sent)."""
    y = attendable[
        (attendable["appointment_datetime"].dt.year == year) & attendable["has_mobile"].astype(bool)
    ]
    dnas = float(y["dna"].sum())
    rr, (rr_lo, rr_hi) = trial.relative_risk, trial.rr_ci
    return Scenario(
        "Cost-message SMS for all mobile patients",
        len(y),
        dnas * (1 - rr),
        dnas * (1 - rr_hi),
        dnas * (1 - rr_lo),
        intervention_cost_gbp=0.0,
    )


def targeted_calls(
    scored: pd.DataFrame,
    annual_appointments: int,
    top_share: float = 0.10,
    effect: float = CALL_EFFECT,
) -> Scenario:
    """Phone the riskiest ``top_share`` of appointments, scaled from the test period."""
    n = len(scored)
    cutoff = scored["risk"].quantile(1 - top_share)
    top = scored[scored["risk"] >= cutoff]
    scale = annual_appointments / n
    expected = top["dna"].sum() * scale
    calls = len(top) * scale
    avoided = expected * effect * CALL_CONTACT_RATE
    return Scenario(
        f"Phone call for top {top_share:.0%} risk",
        int(calls),
        avoided,
        avoided * 0.5,
        avoided * 1.5,
        intervention_cost_gbp=calls * (COST_PER_CALL_GBP + COST_PER_SMS_GBP),
    )
