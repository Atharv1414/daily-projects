"""Was the forecast any good? Scored on mortgages whose fix ended after the model was built."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from mortgage_exits import hazards, survival
from mortgage_exits.config import LEFT, Study


def temporal_split(data: pd.DataFrame, study: Study) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train only on what was known on the split date; test on clocks that started after it."""
    train = data[data["start"] < study.split].copy()
    known = (
        (study.split.year - train["start"].dt.year) * 12
        + study.split.month
        - train["start"].dt.month
    )
    late = train["exit"] > known
    train.loc[late, "cause"] = 0
    train["exit"] = np.minimum(train["exit"], known)
    train = train[train["exit"] > train["entry"]]
    # Mortgages bought part-way through have no forecast to mark: we did not hold them at month 0.
    test = data[(data["start"] >= study.split) & (data["entry"] == 0)]
    return train.reset_index(drop=True), test.reset_index(drop=True)


def censoring_survival(data: pd.DataFrame, months: int) -> np.ndarray:
    """Chance of still being watched at the *start* of each month, 1..months+1."""
    # Within a month exits are seen before the extract cuts off, so censoring counts after events.
    n, _ = survival.risk_table(data["entry"], data["exit"], data["cause"], months, (1,))
    events = np.array(
        [((data["exit"] == t) & (data["cause"] > 0)).sum() for t in range(1, months + 1)]
    )
    lost = np.array(
        [((data["exit"] == t) & (data["cause"] == 0)).sum() for t in range(1, months + 1)]
    )
    left = np.maximum(n - events, 1)
    return np.concatenate([[1.0], np.cumprod(1 - lost / left)])


def ipcw(data: pd.DataFrame, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    """Outcome by the horizon, and weights that stand in for mortgages cut off before it."""
    g = censoring_survival(data, horizon)
    exit_, cause = data["exit"].to_numpy(), data["cause"].to_numpy()
    happened = (exit_ <= horizon) & (cause > 0)
    reached = exit_ >= horizon
    weight = np.zeros(len(data))
    weight[happened] = 1 / g[exit_[happened] - 1]
    still = ~happened & reached
    weight[still] = 1 / g[horizon - 1]
    y = happened & (cause == LEFT)
    return y.astype(float), weight


def brier(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    return float(np.average((y - p) ** 2, weights=w))


def auc(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    """Weighted chance that a leaver is ranked above somebody who did not leave; ties count half."""
    order = np.argsort(p, kind="stable")
    p, y, w = p[order], y[order], w[order]
    _, start = np.unique(p, return_index=True)
    neg = np.add.reduceat(w * (1 - y), start)
    pos = np.add.reduceat(w * y, start)
    if pos.sum() == 0 or neg.sum() == 0:
        raise ValueError("AUC needs some who left and some who did not.")
    below = np.concatenate([[0], np.cumsum(neg)[:-1]])
    return float((pos * (below + neg / 2)).sum() / (pos.sum() * neg.sum()))


def calibration(y: np.ndarray, p: np.ndarray, w: np.ndarray, bins: int = 10) -> pd.DataFrame:
    group = pd.qcut(pd.Series(p).rank(method="first"), bins, labels=False)
    frame = pd.DataFrame({"g": group, "wy": w * y, "wp": w * p, "w": w})
    total = frame.groupby("g").sum()
    out = pd.DataFrame(
        {"predicted": total["wp"] / total["w"], "observed": total["wy"] / total["w"]}
    )
    out["accounts"] = frame.groupby("g").size()
    return out.reset_index(drop=True)


@dataclass
class Backtest:
    scores: pd.DataFrame
    calibration: pd.DataFrame
    predictions: pd.DataFrame
    train_rows: int
    test_rows: int
    differences: pd.DataFrame


def _naive_logit(train: pd.DataFrame, test: pd.DataFrame, horizon: int) -> np.ndarray:
    """The quick model people reach for: keep only finished cases, then fit yes or no."""
    done = train[(train["cause"] > 0) & (train["exit"] <= horizon) & (train["entry"] == 0)]
    x = sm.add_constant(done[hazards.BASELINE].to_numpy(float))
    result = sm.Logit((done["cause"] == LEFT).astype(float).to_numpy(), x).fit(disp=0)
    return result.predict(sm.add_constant(test[hazards.BASELINE].to_numpy(float)))


def backtest(data: pd.DataFrame, rates: pd.Series, study: Study) -> Backtest:
    train, test = temporal_split(data, study)
    h = study.horizon
    models = hazards.fit(hazards.person_months(train, rates, study), hazards.BASELINE)
    p_model = models.cif(test, h)[LEFT - 1, :, h - 1]
    overall = survival.aalen_johansen(train["entry"], train["exit"], train["cause"], h)
    p_flat = np.full(len(test), survival.cif_at(overall, LEFT, h)["cif"])
    recent = train[train["start"] >= study.split - pd.DateOffset(months=18)]
    groups = {
        key: survival.cif_at(
            survival.aalen_johansen(part["entry"], part["exit"], part["cause"], h), LEFT, h
        )["cif"]
        for key, part in recent.groupby(["shock_group", "channel"], observed=True)
        if len(part) >= 100
    }
    keys = zip(test["shock_group"], test["channel"], strict=True)
    p_table = np.array([groups.get(k, p_flat[0]) for k in keys])
    predictions = {
        "Same rate for everyone": p_flat,
        "Finished cases only (logistic)": _naive_logit(train, test, h),
        "Lookup table (shock x channel)": p_table,
        "Competing-risks model": p_model,
    }
    y, w = ipcw(test, h)
    observed = float(np.average(y, weights=w))
    rng = np.random.default_rng(study.seed)
    draws = [rng.integers(0, len(test), len(test)) for _ in range(study.bootstrap)]
    rows, sampled = [], {}
    for name, p in predictions.items():
        sampled[name] = np.array([brier(y[d], p[d], w[d]) for d in draws])
        aucs = [0.5] if np.ptp(p) == 0 else [auc(y[d], p[d], w[d]) for d in draws]
        rows.append(
            {
                "model": name,
                "brier": brier(y, p, w),
                "brier_low": np.percentile(sampled[name], 2.5),
                "brier_high": np.percentile(sampled[name], 97.5),
                "auc": 0.5 if np.ptp(p) == 0 else auc(y, p, w),
                "auc_low": np.percentile(aucs, 2.5),
                "auc_high": np.percentile(aucs, 97.5),
                "mean_predicted": float(np.average(p, weights=w)),
                "observed": observed,
            }
        )
    best = sampled["Competing-risks model"]
    differences = pd.DataFrame(
        [
            {
                "versus": name,
                "gain": (s - best).mean(),
                "low": np.percentile(s - best, 2.5),
                "high": np.percentile(s - best, 97.5),
            }
            for name, s in sampled.items()
            if name != "Competing-risks model"
        ]
    )
    tables = [calibration(y, p, w).assign(model=n) for n, p in predictions.items() if np.ptp(p) > 0]
    detail = test[["account_id", "balance", "shock", "channel"]].assign(p=p_model, y=y, w=w)
    return Backtest(
        pd.DataFrame(rows), pd.concat(tables), detail, len(train), len(test), differences
    )
