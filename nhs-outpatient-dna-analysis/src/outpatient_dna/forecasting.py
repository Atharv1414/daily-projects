"""Weekly DNA forecasting with a rolling-origin backtest against simple baselines.

Operational question: how many DNAs should each week's clinic templates plan for, four
weeks ahead (enough notice to adjust overbooking)? Five candidates are compared on the
same origins and horizons:

* ``naive``: last observed week
* ``ma4``: mean of the last 4 weeks
* ``seasonal_naive``: the same week last year
* ``holt_damped``: Holt's linear trend with damping (statsmodels)
* ``bookings_x_rate``: appointments already booked for the target week, grossed up by the
  historical booking completeness at that horizon, times the trailing 8-week DNA rate.
  This only uses information available at the forecast origin.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

MODELS = ("naive", "ma4", "seasonal_naive", "holt_damped", "bookings_x_rate")


def weekly_series(appointments: pd.DataFrame) -> pd.DataFrame:
    """Weekly attendable volume and DNAs; drops partial first/last weeks."""
    att = appointments[appointments["status"].isin(["attended", "dna"])]
    w = att.groupby("week").agg(appointments=("dna", "size"), dnas=("dna", "sum"))
    w = w.iloc[1:-1] if len(w) > 2 else w
    w["dna_rate"] = w["dnas"] / w["appointments"]
    return w


@dataclass
class Backtest:
    errors: pd.DataFrame  # origin, horizon, model, actual, forecast, abs_error
    summary: pd.DataFrame  # model, mae, mape, bias

    @property
    def best_model(self) -> str:
        return str(self.summary.sort_values("mae").iloc[0]["model"])


class BookingIndex:
    """Answers "how many appointments for week W had been booked by date D?" quickly."""

    def __init__(self, appointments: pd.DataFrame) -> None:
        a = appointments[["week", "booked_date"]].copy()
        self.by_week = {wk: np.sort(g["booked_date"].to_numpy()) for wk, g in a.groupby("week")}

    def booked_by(self, week: pd.Timestamp, as_of: pd.Timestamp) -> int:
        arr = self.by_week.get(week)
        if arr is None:
            return 0
        return int(np.searchsorted(arr, np.datetime64(as_of), side="right"))


def _forecast(
    model: str,
    hist: pd.DataFrame,
    target: pd.Timestamp,
    horizon: int,
    series: pd.DataFrame,
    idx: BookingIndex,
    origin: pd.Timestamp,
) -> float:
    dnas = hist["dnas"].astype(float)
    if model == "naive":
        return float(dnas.iloc[-1])
    if model == "ma4":
        return float(dnas.iloc[-4:].mean())
    if model == "seasonal_naive":
        last_year = target - pd.Timedelta(weeks=52)
        return float(series["dnas"].get(last_year, dnas.iloc[-1]))
    if model == "holt_damped":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(
                dnas.to_numpy(), trend="add", damped_trend=True, initialization_method="estimated"
            ).fit()
        return float(fit.forecast(horizon)[-1])
    if model == "bookings_x_rate":
        recent = hist.iloc[-8:]
        rate = recent["dnas"].sum() / recent["appointments"].sum()
        ratios = []
        for wk in recent.index:
            # Same lead as the live forecast: cut-off = end of the week `horizon` weeks back.
            booked = idx.booked_by(wk, wk - pd.Timedelta(weeks=horizon) + pd.Timedelta(days=6))
            ratios.append(booked / series.loc[wk, "appointments"])
        completeness = float(np.mean(ratios)) or 1.0
        return idx.booked_by(target, origin) / completeness * rate
    raise ValueError(f"unknown model {model}")


def backtest(
    appointments: pd.DataFrame,
    horizon: int = 4,
    n_origins: int = 26,
    models: tuple[str, ...] = MODELS,
) -> Backtest:
    series = weekly_series(appointments)
    idx = BookingIndex(appointments)
    rows = []
    last_origin = len(series) - horizon
    for o in range(last_origin - n_origins, last_origin):
        hist = series.iloc[: o + 1]
        origin_week = series.index[o]
        origin_date = origin_week + pd.Timedelta(days=6)  # end of the origin week
        for h in range(1, horizon + 1):
            target = series.index[o + h]
            actual = float(series.iloc[o + h]["dnas"])
            for m in models:
                f = _forecast(m, hist, target, h, series, idx, origin_date)
                rows.append((origin_week, h, m, actual, f, abs(actual - f)))
    errors = pd.DataFrame(
        rows, columns=["origin", "horizon", "model", "actual", "forecast", "abs_error"]
    )
    summary = (
        errors.groupby("model")
        .apply(
            lambda g: pd.Series(
                {
                    "mae": g["abs_error"].mean(),
                    "mape": (g["abs_error"] / g["actual"]).mean() * 100,
                    "bias": (g["forecast"] - g["actual"]).mean(),
                }
            ),
            include_groups=False,
        )
        .reset_index()
        .sort_values("mae")
        .reset_index(drop=True)
    )
    return Backtest(errors, summary)
