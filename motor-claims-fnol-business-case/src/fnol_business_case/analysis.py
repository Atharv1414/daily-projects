"""Supporting data analysis: current-state baseline and the digital FNOL pilot evaluation.

The financial model takes its key assumptions from here, so every benefit can be traced back
to evidence in the claims data rather than to a vendor's brochure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

from fnol_business_case.datagen import PILOT_START

PRE = (date(2025, 11, 1), date(2026, 4, 30))
POST = (date(2026, 5, 1), date(2026, 8, 22))  # cut-off limits right-censoring of open claims
MAX_HANDLE_MINUTES = 180


@dataclass
class CleaningLog:
    steps: list[tuple[str, int]] = field(default_factory=list)

    def add(self, step: str, rows: int) -> None:
        self.steps.append((step, int(rows)))


def load(path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["notified_at"])


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, CleaningLog]:
    log = CleaningLog()
    out = df.copy()
    log.add("rows received", len(out))
    dupes = out.duplicated("claim_id")
    log.add("duplicate claim ids removed", dupes.sum())
    out = out[~dupes]
    mis = out.fnol_handle_minutes > MAX_HANDLE_MINUTES
    log.add(f"handle time > {MAX_HANDLE_MINUTES} min set to missing (mis-keyed seconds)", mis.sum())
    out.loc[mis, "fnol_handle_minutes"] = np.nan
    log.add(
        "handle time missing (excluded from handle-time stats)",
        out.fnol_handle_minutes.isna().sum(),
    )
    log.add(
        "open claims (no settlement time; excluded from cycle-time stats)",
        out.status.eq("Open").sum(),
    )
    log.add("total losses (kept; excluded from leakage baseline)", out.is_total_loss.sum())
    log.add("claims without an NPS response", out.nps_score.isna().sum())
    out["month"] = out.notified_at.dt.to_period("M").astype(str)
    out["notified_date"] = out.notified_at.dt.date
    return out.reset_index(drop=True), log


def nps(scores: pd.Series) -> float:
    s = scores.dropna()
    if s.empty:
        return float("nan")
    return float(((s >= 9).mean() - (s <= 6).mean()) * 100)


def baseline(df: pd.DataFrame) -> dict[str, float]:
    """Current-state KPIs for the 12 months before the pilot (May 2025 to Apr 2026)."""
    b = df[(df.notified_date >= date(2025, 5, 1)) & (df.notified_date <= date(2026, 4, 30))]
    settled = b[b.status == "Settled"]
    phone = b[b.channel == "Phone"]
    rental = b[b.rental_days > 0]
    return {
        "annual_claims": float(len(b)),
        "phone_share": float((b.channel == "Phone").mean()),
        "phone_handle_minutes": float(phone.fnol_handle_minutes.mean()),
        "mean_days_to_settle": float(settled.days_to_settle.mean()),
        "median_days_to_settle": float(settled.days_to_settle.median()),
        "rental_share": float((b.rental_days > 0).mean()),
        "rental_cost_per_day": float(rental.rental_cost_gbp.sum() / rental.rental_days.sum()),
        "mean_rental_days": float(rental.rental_days.mean()),
        "mean_indemnity": float(b[~b.is_total_loss].indemnity_gbp.mean()),
        "complaint_rate": float(b.complaint.mean()),
        "fraud_referral_rate": float(b.fraud_referred.mean()),
        "fraud_confirm_rate": float(b[b.fraud_referred].fraud_confirmed.mean()),
        "nps": nps(b.nps_score),
        "total_rental_cost": float(b.rental_cost_gbp.sum()),
    }


@dataclass(frozen=True)
class Comparison:
    metric: str
    digital_mean: float
    phone_mean: float
    difference: float
    ci_low: float
    ci_high: float
    p_value: float
    cohens_d: float
    n_digital: int
    n_phone: int


def _welch(metric: str, a: pd.Series, b: pd.Series) -> Comparison:
    a, b = a.dropna().astype(float), b.dropna().astype(float)
    t = stats.ttest_ind(a, b, equal_var=False)
    diff = a.mean() - b.mean()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    dof = se**4 / (
        (a.var(ddof=1) / len(a)) ** 2 / (len(a) - 1) + (b.var(ddof=1) / len(b)) ** 2 / (len(b) - 1)
    )
    half = stats.t.ppf(0.975, dof) * se
    pooled = np.sqrt(
        ((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2)
    )
    return Comparison(
        metric,
        a.mean(),
        b.mean(),
        diff,
        diff - half,
        diff + half,
        float(t.pvalue),
        diff / pooled,
        len(a),
        len(b),
    )


def channel_comparison(df: pd.DataFrame) -> list[Comparison]:
    """Digital vs phone FNOL for *simple* claims in the pilot regions after launch.

    Observational: customers choose the channel, so these differences include selection
    effects. The difference-in-differences below is the causal estimate the case relies on.
    """
    p = df[df.in_pilot_region & (df.notified_date >= PILOT_START) & df.is_simple]
    dig, ph = p[p.channel == "Digital"], p[p.channel == "Phone"]
    return [
        _welch("FNOL handle minutes", dig.fnol_handle_minutes, ph.fnol_handle_minutes),
        _welch("Days to first contact", dig.days_to_first_contact, ph.days_to_first_contact),
        _welch("Days to settle", dig.days_to_settle, ph.days_to_settle),
        _welch("NPS score (0-10)", dig.nps_score, ph.nps_score),
    ]


@dataclass(frozen=True)
class DiDResult:
    estimate: float
    ci_low: float
    ci_high: float
    cells: dict[str, float]
    digital_share_post: float
    per_digital_claim: float
    per_digital_ci: tuple[float, float]
    pre_trend_slope: float
    pre_trend_p: float


def difference_in_differences(df: pd.DataFrame, n_boot: int = 1_000, seed: int = 3) -> DiDResult:
    """DiD on days-to-settle: pilot vs control regions, pre vs post launch.

    The estimate is an intention-to-treat effect per claim in pilot regions. Dividing by the
    digital take-up gives a Wald-style effect per digital claim, which is what the financial
    model needs. The CI comes from a bootstrap that resamples claims within each cell.
    """
    s = df[(df.status == "Settled") & df.days_to_settle.notna()].copy()

    def cell(treat: bool, period: tuple[date, date]) -> np.ndarray:
        m = (
            (s.in_pilot_region == treat)
            & (s.notified_date >= period[0])
            & (s.notified_date <= period[1])
        )
        return s.loc[m, "days_to_settle"].to_numpy(float)

    tp, tq, cp, cq = cell(True, PRE), cell(True, POST), cell(False, PRE), cell(False, POST)
    est = (tq.mean() - tp.mean()) - (cq.mean() - cp.mean())
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        r = [rng.choice(x, x.size) for x in (tp, tq, cp, cq)]
        boots[i] = (r[1].mean() - r[0].mean()) - (r[3].mean() - r[2].mean())
    lo, hi = np.percentile(boots, [2.5, 97.5])

    post_pilot = df[
        df.in_pilot_region & (df.notified_date >= POST[0]) & (df.notified_date <= POST[1])
    ]
    share = float((post_pilot.channel == "Digital").mean())

    # Parallel-trends check: the monthly pilot-minus-control gap before launch should be flat.
    pre = s[(s.notified_date >= date(2025, 1, 1)) & (s.notified_date < PILOT_START)]
    gap = pre.groupby(["month", "in_pilot_region"]).days_to_settle.mean().unstack()
    diff = (gap[True] - gap[False]).dropna()
    reg = stats.linregress(np.arange(len(diff)), diff.to_numpy())
    return DiDResult(
        float(est),
        float(lo),
        float(hi),
        {
            "pilot_pre": tp.mean(),
            "pilot_post": tq.mean(),
            "control_pre": cp.mean(),
            "control_post": cq.mean(),
        },
        share,
        float(est / share),
        (float(lo / share), float(hi / share)),
        float(reg.slope),
        float(reg.pvalue),
    )


@dataclass(frozen=True)
class RentalLink:
    slope_rental_days_per_cycle_day: float
    r_squared: float
    n: int


def rental_vs_cycle(df: pd.DataFrame) -> RentalLink:
    """How many hire-car days does one extra day of claim cycle time cost? (OLS)"""
    r = df[(df.rental_days > 0) & df.days_to_settle.notna()]
    fit = stats.linregress(r.days_to_settle, r.rental_days)
    return RentalLink(float(fit.slope), float(fit.rvalue**2), len(r))


def monthly(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["month", "channel"]).size().unstack(fill_value=0)
    return g


def summary_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    b = df[(df.notified_date >= date(2025, 5, 1)) & (df.notified_date <= date(2026, 4, 30))]
    by_type = (
        b.groupby("claim_type")
        .agg(
            claims=("claim_id", "size"),
            mean_indemnity=("indemnity_gbp", "mean"),
            mean_days_to_settle=("days_to_settle", "mean"),
            rental_share=("rental_days", lambda x: (x > 0).mean()),
            simple_share=("is_simple", "mean"),
        )
        .sort_values("claims", ascending=False)
    )
    by_channel = b.groupby("channel").agg(
        claims=("claim_id", "size"),
        handle_minutes=("fnol_handle_minutes", "mean"),
        days_to_first_contact=("days_to_first_contact", "mean"),
        complaint_rate=("complaint", "mean"),
    )
    return {"by_type": by_type, "by_channel": by_channel}
