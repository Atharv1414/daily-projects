"""Seeded motor-claims data for "Albion Mutual", a fictional UK motor insurer.

24 months of claims (Nov 2024 to Oct 2026, ~60k claims). A digital first-notification-of-loss
(FNOL) pilot started on 1 May 2026 in two regions (North West and Scotland); every other region
is a control. The pilot effect is built in so the analysis has something real to find, but the
data is deliberately messy: open claims have no settlement date, NPS is only known for survey
respondents, some handle times are missing or mis-keyed, and a few total-loss outliers exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REGIONS = [
    "Scotland",
    "North East",
    "North West",
    "Yorkshire",
    "Midlands",
    "Wales",
    "South West",
    "South East",
    "London",
]
REGION_W = [0.08, 0.06, 0.13, 0.10, 0.17, 0.05, 0.10, 0.15, 0.16]
PILOT_REGIONS = ("North West", "Scotland")
PILOT_START = date(2026, 5, 1)

# claim type: (share, mean indemnity £, sd log, simple-claim share, rental probability)
CLAIM_TYPES = {
    "Windscreen": (0.22, 420, 0.30, 0.95, 0.02),
    "Single-vehicle collision": (0.20, 3_100, 0.55, 0.60, 0.45),
    "Third-party collision": (0.30, 5_200, 0.65, 0.35, 0.65),
    "Theft": (0.07, 7_800, 0.60, 0.20, 0.55),
    "Vandalism": (0.08, 1_400, 0.50, 0.70, 0.25),
    "Weather / flood": (0.05, 3_900, 0.70, 0.40, 0.40),
    "Parking / low speed": (0.08, 1_150, 0.45, 0.85, 0.20),
}


@dataclass(frozen=True)
class GenConfig:
    seed: int = 11
    claims_per_month: int = 2_500
    out_dir: Path = Path("data/generated")


def generate_claims(cfg: GenConfig = GenConfig()) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.seed)
    months = pd.period_range("2024-11", "2026-10", freq="M")
    season = {12: 1.18, 1: 1.22, 2: 1.10, 11: 1.08, 7: 0.92, 8: 0.90}
    frames = []
    for m in months:
        n = int(rng.poisson(cfg.claims_per_month * season.get(m.month, 1.0)))
        day = rng.integers(0, m.days_in_month, n)
        notified = (
            m.start_time
            + pd.to_timedelta(day, unit="D")
            + pd.to_timedelta(rng.integers(6 * 60, 23 * 60, n), unit="m")
        )
        frames.append(pd.DataFrame({"notified_at": notified}))
    df = pd.concat(frames, ignore_index=True)
    n = len(df)
    df["claim_id"] = [f"AMC-{i:06d}" for i in range(n)]
    df["region"] = rng.choice(REGIONS, n, p=REGION_W)
    types = list(CLAIM_TYPES)
    df["claim_type"] = rng.choice(types, n, p=[CLAIM_TYPES[t][0] for t in types])
    simple_p = df.claim_type.map(lambda t: CLAIM_TYPES[t][3]).to_numpy()
    df["is_simple"] = rng.random(n) < simple_p

    in_pilot = (
        df.region.isin(PILOT_REGIONS).to_numpy()
        & (df.notified_at.dt.date >= PILOT_START).to_numpy()
    )
    # Channel mix: phone dominates; in pilot regions ~38% of new claims go digital, more for
    # simple claims. Brokers notify ~9% of claims everywhere.
    p_digital = np.where(in_pilot, np.where(df.is_simple, 0.46, 0.24), 0.0)
    roll = rng.random(n)
    df["channel"] = np.select(
        [roll < 0.09, roll < 0.09 + p_digital, roll < 0.09 + p_digital + 0.05],
        ["Broker", "Digital", "Email"],
        default="Phone",
    )
    digital = df.channel.eq("Digital").to_numpy()

    # FNOL handling minutes: a phone FNOL is a long structured call; a digital FNOL needs a
    # short handler review of the submitted form and photos.
    base_handle = np.where(
        df.channel.eq("Phone"),
        rng.gamma(9, 2.7, n),
        np.where(df.channel.eq("Email"), rng.gamma(6, 3.2, n), rng.gamma(5, 3.0, n)),
    )
    df["fnol_handle_minutes"] = np.where(digital, rng.gamma(3, 2.1, n), base_handle).round(1)
    bad = rng.random(n) < 0.004  # mis-keyed handle times (seconds keyed as minutes)
    df.loc[bad, "fnol_handle_minutes"] *= 60
    df.loc[rng.random(n) < 0.02, "fnol_handle_minutes"] = np.nan

    # Lifecycle: days to settle grows with complexity; digital claims skip the call-back
    # queue and arrive with photos, saving time mostly on simple claims.
    sev = df.claim_type.map(lambda t: CLAIM_TYPES[t][1]).to_numpy()
    first_contact = rng.gamma(2.0, 0.9, n) + np.where(df.channel.eq("Email"), 1.5, 0.0)
    first_contact = np.where(digital, rng.gamma(1.2, 0.4, n), first_contact)
    cycle = (np.where(df.is_simple, 9.0, 21.0) + sev / 900) * rng.lognormal(0, 0.35, n)
    cycle = cycle - np.where(digital, np.where(df.is_simple, 3.4, 1.6), 0.0)
    trend = (df.notified_at - df.notified_at.min()).dt.days.to_numpy() / 730  # slow drift
    cycle = np.maximum(1.0, cycle + 0.8 * trend + first_contact)
    df["days_to_first_contact"] = first_contact.round(1)
    df["days_to_settle"] = cycle.round(0)

    sd = df.claim_type.map(lambda t: CLAIM_TYPES[t][2]).to_numpy()
    indemnity = rng.lognormal(np.log(sev) - sd**2 / 2, sd)
    leakage = np.where(digital, 0.012, 0.025) * rng.random(n) * 2  # overpayment share
    indemnity = indemnity * (1 + leakage)
    total_loss = (rng.random(n) < 0.015) & ~df.claim_type.eq("Windscreen").to_numpy()
    indemnity[total_loss] = rng.uniform(9_000, 38_000, total_loss.sum())
    df["indemnity_gbp"] = indemnity.round(2)

    rental_p = df.claim_type.map(lambda t: CLAIM_TYPES[t][4]).to_numpy()
    has_rental = rng.random(n) < rental_p
    rental_days = np.where(
        has_rental, np.maximum(1, np.round(cycle * rng.uniform(0.55, 0.85, n))), 0
    )
    df["rental_days"] = rental_days.astype(int)
    df["rental_cost_gbp"] = (rental_days * rng.normal(46, 6, n).clip(30)).round(2)

    fraud_p = np.where(df.claim_type.isin(["Theft", "Third-party collision"]), 0.035, 0.012)
    df["fraud_referred"] = rng.random(n) < fraud_p
    df["fraud_confirmed"] = df.fraud_referred & (rng.random(n) < np.where(digital, 0.42, 0.33))
    df["complaint"] = rng.random(n) < (0.018 + cycle / 2_000)

    # NPS survey: ~18% respond. Score falls with cycle time; digital adds a small uplift.
    resp = rng.random(n) < 0.18
    score = np.clip(
        np.round(10.4 - cycle / 6 + np.where(digital, 0.6, 0) + rng.normal(0, 1.8, n)), 0, 10
    )
    df["nps_score"] = np.where(resp, score, np.nan)

    # Claims notified in the last weeks may still be open: no settlement data yet.
    as_of = pd.Timestamp("2026-10-31 23:59")
    settled_at = df.notified_at + pd.to_timedelta(df.days_to_settle, unit="D")
    open_ = settled_at > as_of
    df["status"] = np.where(open_, "Open", "Settled")
    df.loc[open_, ["days_to_settle"]] = np.nan
    df["in_pilot_region"] = df.region.isin(PILOT_REGIONS)
    df["is_total_loss"] = total_loss
    cols = [
        "claim_id",
        "notified_at",
        "region",
        "in_pilot_region",
        "channel",
        "claim_type",
        "is_simple",
        "fnol_handle_minutes",
        "days_to_first_contact",
        "days_to_settle",
        "status",
        "indemnity_gbp",
        "is_total_loss",
        "rental_days",
        "rental_cost_gbp",
        "fraud_referred",
        "fraud_confirmed",
        "complaint",
        "nps_score",
    ]
    return df[cols].sort_values("notified_at").reset_index(drop=True)


def save(df: pd.DataFrame, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "claims.csv"
    df.to_csv(path, index=False)
    return path
