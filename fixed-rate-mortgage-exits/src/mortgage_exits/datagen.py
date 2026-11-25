"""Synthetic mortgage book with realistic mess. Nothing here describes a real lender.

The true hazards are written down in TRUE_EFFECTS, so the tests can check that the models find them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mortgage_exits.config import Study

REGIONS = ["London", "South East", "Midlands", "North West", "Scotland", "Wales"]
SVR_MARGIN = 2.6

# Effects on the log of the monthly hazard.
TRUE_EFFECTS: dict[int, dict[str, float]] = {
    1: {"incentive": 0.10, "shock": -0.6, "broker": -0.35, "ltv10": 0.12, "older": 0.10},
    2: {"incentive": 0.30, "shock": 1.6, "broker": 0.55, "ltv10": -0.22, "older": -0.15},
    3: {"incentive": 0.02, "shock": 0.3, "broker": 0.0, "ltv10": -0.12, "older": 0.40},
    4: {"incentive": 0.05, "shock": 2.4, "broker": 0.1, "ltv10": 0.25, "older": -0.20},
}
# Monthly base rates by month on the clock (1 to 24). The fix ends after month 6.
_BASE = {
    1: [0.02, 0.03, 0.05, 0.07, 0.10, 0.17, 0.09, 0.05, 0.035, 0.03] + [0.022] * 14,
    2: [0.002, 0.003, 0.006, 0.010, 0.022, 0.08, 0.036, 0.022, 0.016, 0.014] + [0.011] * 14,
    3: [0.002] * 5 + [0.012, 0.014] + [0.006] * 17,
    4: [0.0004] * 6 + [0.0014] * 18,
}


@dataclass(frozen=True)
class RawData:
    accounts: pd.DataFrame
    events: pd.DataFrame
    rates: pd.DataFrame


def market_rates() -> pd.Series:
    """Two-year fixed rate by month: flat, a steep rise, then a slow fall."""
    months = pd.date_range("2016-01-01", "2027-12-01", freq="MS")
    x = np.arange(len(months))
    knots = pd.to_datetime(
        [
            "2016-01-01",
            "2020-01-01",
            "2021-09-01",
            "2022-07-01",
            "2022-11-01",
            "2023-08-01",
            "2024-09-01",
            "2025-06-01",
            "2026-06-01",
            "2027-12-01",
        ]
    )
    values = [2.4, 2.0, 1.6, 3.4, 5.6, 6.1, 4.9, 4.5, 4.1, 3.9]
    at = [(k.year - 2016) * 12 + k.month - 1 for k in knots]
    return pd.Series(np.interp(x, at, values).round(2), index=months, name="rate")


def monthly_payment(balance: np.ndarray, rate: np.ndarray, years: np.ndarray) -> np.ndarray:
    """Repayment on a capital and interest mortgage; rate is a yearly percentage."""
    r = np.asarray(rate) / 1200
    n = np.asarray(years) * 12
    return np.asarray(balance) * r / (1 - (1 + r) ** -n)


def generate(study: Study) -> RawData:
    rng = np.random.default_rng(study.seed)
    n = study.accounts
    rates = market_rates()
    maturity = pd.to_datetime("2023-01-01") + pd.to_timedelta(rng.integers(0, 1180, n), "D")
    maturity = pd.Series(maturity).dt.to_period("M").dt.to_timestamp()
    term = rng.choice([2, 5], n, p=[0.55, 0.45])
    opened = maturity - pd.to_timedelta(term * 365.25, "D")
    opened = opened.dt.to_period("M").dt.to_timestamp()
    ltv = np.clip(rng.beta(5, 2.6, n) * 100, 15, 95)
    fixed = (
        rates.reindex(opened).to_numpy() + (ltv - 65) * 0.012 + np.where(term == 5, 0.15, 0)
    ) + rng.normal(0, 0.18, n)
    fixed = np.clip(fixed, 1.05, 7.5).round(2)
    balance = np.clip(rng.lognormal(11.95, 0.55, n), 20_000, 1_200_000).round(0)
    age = np.clip(rng.normal(41, 10.5, n), 21, 78).round(0)
    years_left = np.clip(68 - age + rng.normal(0, 4, n), 6, 35).round(0)
    broker = rng.random(n) < 0.62
    start = maturity - pd.DateOffset(months=study.lead_months)
    start_rate = rates.reindex(start).to_numpy()
    shock = (
        monthly_payment(balance, start_rate, years_left)
        / monthly_payment(balance, fixed, years_left)
        - 1
    )
    cause, month = _simulate(rng, study, start, fixed, shock, broker, ltv, age, rates)

    # An acquired book: seen only from the day it was bought, and only if still open by then.
    bought = rng.random(n) < 0.14
    entry = np.where(bought, rng.integers(1, 11, n), 0)
    gone = bought & (month <= entry) & (cause > 0)
    frame = pd.DataFrame(
        {
            "account_id": [f"M{i:06d}" for i in range(n)],
            "fix_end": maturity,
            "opened": opened,
            "fix_years": term,
            "fixed_rate": fixed,
            "balance": balance,
            "ltv": ltv.round(1),
            "age": age,
            "years_left": years_left,
            "channel": np.where(broker, "Broker", "Direct"),
            "region": rng.choice(REGIONS, n, p=[0.17, 0.21, 0.2, 0.18, 0.14, 0.1]),
            "acquired_on": [
                s + pd.DateOffset(months=int(e)) if b else pd.NaT
                for s, e, b in zip(start, entry, bought, strict=True)
            ],
            "_cause": cause,
            "_month": month,
            "_start": start,
        }
    )[~gone].reset_index(drop=True)
    # Loans bought after the extract are not ours yet.
    frame = frame[~(frame["acquired_on"] > study.extract)].reset_index(drop=True)
    events = _events(rng, frame, study)
    return RawData(
        accounts=_dirty_accounts(rng, frame), events=events, rates=_dirty_rates(rng, rates)
    )


def _simulate(rng, study, start, fixed, shock, broker, ltv, age, rates):
    n = len(fixed)
    cause = np.zeros(n, dtype=int)
    month = np.full(n, study.max_month)
    alive = np.ones(n, dtype=bool)
    for m in range(1, study.max_month + 1):
        when = start + pd.DateOffset(months=m - 1)
        market = rates.reindex(when).to_numpy()
        pay = np.where(m <= study.lead_months, fixed, market + SVR_MARGIN)
        # Before the fix ends nobody saves by moving; they move to dodge the reversion rate.
        incentive = np.clip(pay - market, -2, 4)
        hazards = []
        for k, effect in TRUE_EFFECTS.items():
            eta = (
                effect["incentive"] * incentive
                + effect["shock"] * shock
                + effect["broker"] * broker
                + effect["ltv10"] * (ltv - 65) / 10
                + effect["older"] * (age > 50)
            )
            hazards.append(-np.expm1(-_BASE[k][m - 1] * np.exp(eta)))
        h = np.array(hazards)
        total = h.sum(axis=0)
        h = np.where(total > 0.95, h * 0.95 / total, h)
        draw = rng.random(n)
        edges = np.cumsum(h, axis=0)
        hit = (draw[None, :] < edges).argmax(axis=0) + 1
        happened = alive & (draw < edges[-1])
        cause[happened] = hit[happened]
        month[happened] = m
        alive &= ~happened
    return cause, month


def _events(rng, frame: pd.DataFrame, study: Study) -> pd.DataFrame:
    codes = {
        1: ["PRODUCT_TRANSFER"],
        2: ["REDEMPTION:REMORTGAGE"],
        3: ["REDEMPTION:SALE", "REDEMPTION:REPAID"],
        4: ["ARREARS_90"],
    }
    happened = frame[frame["_cause"] > 0]
    dates = [
        s + pd.DateOffset(months=int(m)) - pd.Timedelta(days=int(d))
        for s, m, d in zip(
            happened["_start"], happened["_month"], rng.integers(1, 27, len(happened)), strict=True
        )
    ]
    events = pd.DataFrame(
        {
            "account_id": happened["account_id"].to_numpy(),
            "event_date": dates,
            "code": [rng.choice(codes[c]) for c in happened["_cause"]],
            "status": "COMPLETED",
        }
    )
    events = events[events["event_date"] <= study.extract]
    started = frame.sample(frac=0.10, random_state=int(rng.integers(1e9)))
    cancelled = pd.DataFrame(
        {
            "account_id": started["account_id"].to_numpy(),
            "event_date": (started["_start"] + pd.DateOffset(months=3)).to_numpy(),
            "code": "REDEMPTION:REMORTGAGE",
            "status": "CANCELLED",
        }
    )
    cancelled = cancelled[cancelled["event_date"] <= study.extract]
    # Systems that keep writing after a loan has gone, repeated feeds and unknown accounts.
    echo = events.sample(frac=0.03, random_state=1).assign(
        code="ARREARS_90", event_date=lambda d: d["event_date"] + pd.Timedelta(days=70)
    )
    again = events.sample(frac=0.02, random_state=2)
    orphan = events.sample(frac=0.004, random_state=3).assign(
        account_id=lambda d: "X" + d["account_id"].str[1:]
    )
    out = pd.concat([events, cancelled, echo, again, orphan], ignore_index=True)
    out["event_date"] = pd.to_datetime(out["event_date"]).dt.strftime("%Y-%m-%d")
    return out.sample(frac=1, random_state=4).reset_index(drop=True)


def _dirty_accounts(rng, frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.drop(columns=["_cause", "_month", "_start"]).copy()
    n = len(out)
    ltv = out["ltv"].map("{:.1f}".format).astype(object)
    style = rng.random(n)
    ltv[style < 0.2] = out["ltv"][style < 0.2].map("{:.1f}%".format)
    ltv[style > 0.9] = out["ltv"][style > 0.9].map(lambda v: f"{v / 100:.3f}")
    ltv[(style > 0.4) & (style < 0.415)] = None
    out["ltv"] = ltv
    pence = rng.random(n) < 0.006
    out.loc[pence, "balance"] = out.loc[pence, "balance"] * 100
    out["region"] = out["region"].where(rng.random(n) > 0.05, out["region"].str.upper() + " ")
    out["age"] = out["age"].where(rng.random(n) > 0.012)
    out.loc[rng.random(n) < 0.002, "age"] = 999
    for column in ["fix_end", "opened", "acquired_on"]:
        out[column] = out[column].dt.strftime("%Y-%m-%d")
    uk = rng.random(n) < 0.15
    out.loc[uk, "fix_end"] = pd.to_datetime(out.loc[uk, "fix_end"]).dt.strftime("%d/%m/%Y")
    again = out.sample(frac=0.008, random_state=5)
    return pd.concat([out, again], ignore_index=True).sample(frac=1, random_state=6)


def _dirty_rates(rng, rates: pd.Series) -> pd.DataFrame:
    frame = rates.rename_axis("month").reset_index()
    lost = rng.choice(np.arange(20, len(frame) - 20), 4, replace=False)
    frame.loc[lost, "rate"] = np.nan
    return frame
