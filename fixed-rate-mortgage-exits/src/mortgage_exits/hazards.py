"""Cause-specific discrete-time hazard models, and the cumulative incidence they imply.

Exits are recorded by month, so time is discrete. A complementary log-log link makes each
coefficient a log hazard ratio, the same reading a Cox model would give.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from mortgage_exits.cleaning import SVR_MARGIN
from mortgage_exits.config import CAUSES, Study

BASELINE = ["shock", "broker", "ltv10", "older"]
EXPLAIN = ["incentive", *BASELINE]
_FULL_BINS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 18, 24]
_RARE_BINS = [0, 6, 12, 24]  # arrears are too few for a term per month


class ModelError(RuntimeError):
    """A model could not be fitted or used."""


def bins_for(cause: int) -> list[int]:
    return _RARE_BINS if cause == 4 else _FULL_BINS


def month_terms(month: np.ndarray, cause: int) -> np.ndarray:
    bins = bins_for(cause)
    which = np.digitize(month, bins, right=True) - 1
    return np.eye(len(bins) - 1)[np.clip(which, 0, len(bins) - 2)]


def person_months(data: pd.DataFrame, rates: pd.Series, study: Study) -> pd.DataFrame:
    """One row for each month a mortgage was at risk, with what was known in that month."""
    length = (data["exit"] - data["entry"]).to_numpy()
    index = np.repeat(np.arange(len(data)), length)
    position = np.arange(len(index)) - np.repeat(np.cumsum(length) - length, length)
    out = data.iloc[index].reset_index(drop=True)
    out["month"] = out["entry"].to_numpy() + 1 + position
    last = out["month"] == out["exit"]
    out["y"] = np.where(last, out["cause"], 0)
    # Month 1 of the clock is the calendar month in which it starts.
    calendar = (
        out["start"].dt.year * 12
        + out["start"].dt.month
        + out["month"]
        - 2
        - rates.index[0].year * 12
    )
    market = rates.to_numpy()[calendar.to_numpy()]
    pays = np.where(out["month"] <= study.lead_months, out["fixed_rate"], market + SVR_MARGIN)
    out["incentive"] = np.clip(pays - market, -2, 4)
    return out


@dataclass
class HazardModels:
    features: list[str]
    params: dict[int, np.ndarray]
    covariance: dict[int, np.ndarray]
    events: dict[int, int]

    def hazards(self, frame: pd.DataFrame, month: np.ndarray) -> np.ndarray:
        """Monthly hazard for each cause: array of causes by rows."""
        x = frame[self.features].to_numpy(float)
        rows = []
        for k, beta in self.params.items():
            design = np.hstack([month_terms(month, k), x])
            rows.append(-np.expm1(-np.exp(np.clip(design @ beta, -30, 3))))
        h = np.array(rows)
        total = h.sum(axis=0)
        return np.where(total > 1, h / np.maximum(total, 1), h)

    def cif(self, frame: pd.DataFrame, months: int) -> np.ndarray:
        """Cumulative incidence from month 0: array of causes by rows by months."""
        survival = np.ones(len(frame))
        total = np.zeros((len(self.params), len(frame)))
        out = np.empty((len(self.params), len(frame), months))
        for t in range(1, months + 1):
            h = self.hazards(frame, np.full(len(frame), t))
            total = total + survival * h
            survival = survival * (1 - h.sum(axis=0))
            out[:, :, t - 1] = total
        return out

    def hazard_ratios(self) -> pd.DataFrame:
        rows = []
        for k, beta in self.params.items():
            offset = len(bins_for(k)) - 1
            se = np.sqrt(np.diag(self.covariance[k]))[offset:]
            for name, b, s in zip(self.features, beta[offset:], se, strict=True):
                rows.append((k, name, b, s))
        out = pd.DataFrame(rows, columns=["cause", "feature", "log_hr", "se"])
        out["hr"] = np.exp(out["log_hr"])
        out["low"] = np.exp(out["log_hr"] - 1.96 * out["se"])
        out["high"] = np.exp(out["log_hr"] + 1.96 * out["se"])
        return out


def fit(panel: pd.DataFrame, features: list[str]) -> HazardModels:
    params, covariance, events = {}, {}, {}
    x = panel[features].to_numpy(float)
    if not np.isfinite(x).all():
        raise ModelError("A feature has missing or infinite values.")
    for k in CAUSES:
        y = (panel["y"] == k).to_numpy(float)
        events[k] = int(y.sum())
        if events[k] < 5 * len(features):
            raise ModelError(f"Only {events[k]} events for cause {k}: too few to model.")
        design = np.hstack([month_terms(panel["month"].to_numpy(), k), x])
        # A month with no events of this kind has a hazard of zero, not a coefficient of minus
        # infinity, so its rows are left out of the fit.
        used = design[:, : len(bins_for(k)) - 1].T @ y
        empty = np.flatnonzero(used == 0)
        keep = np.setdiff1d(np.arange(design.shape[1]), empty)
        rows = design[:, empty].sum(axis=1) == 0
        family = sm.families.Binomial(link=sm.families.links.CLogLog())
        result = sm.GLM(y[rows], design[np.ix_(rows, keep)], family=family).fit()
        if not result.converged:
            raise ModelError(f"The model for cause {k} did not converge.")
        beta = np.full(design.shape[1], -30.0)
        beta[keep] = result.params
        cov = np.zeros((design.shape[1], design.shape[1]))
        cov[np.ix_(keep, keep)] = result.cov_params()
        params[k], covariance[k] = beta, cov
    return HazardModels(list(features), params, covariance, events)
