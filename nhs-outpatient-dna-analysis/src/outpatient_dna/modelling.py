"""Logistic regression risk model: odds ratios, out-of-time validation, calibration, lift."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import rankdata

FORMULA = (
    "dna ~ C(age_band, Treatment('45-64')) + imd_c + imd_missing + np.log1p(lead_days)"
    " + C(appointment_type, Treatment('Follow-up'))"
    " + C(contact_mode, Treatment('Face to face')) + C(weekday, Treatment('Wed'))"
    " + C(specialty, Treatment('Respiratory')) + C(prior_dnas) + distance_km + has_mobile"
)
SPLIT_DATE = pd.Timestamp("2025-07-01")


@dataclass
class ModelResult:
    odds_ratios: pd.DataFrame  # term, or, ci_low, ci_high, p_value
    auc_train: float
    auc_test: float
    brier_test: float
    base_rate_test: float
    calibration: pd.DataFrame  # decile, predicted, observed, n
    top_decile_capture: float  # share of test DNAs in the riskiest 10%
    n_train: int
    n_test: int
    test_scored: pd.DataFrame


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=["age_band"]).copy()
    d["imd_missing"] = d["imd_decile"].isna().astype(int)
    d["imd_c"] = d["imd_decile"].fillna(d["imd_decile"].median()) - 5.5
    d["has_mobile"] = d["has_mobile"].astype(int)
    return d


def auc(y_true: np.ndarray, score: np.ndarray) -> float:
    """ROC AUC via the Mann-Whitney U statistic (ties get average ranks)."""
    y = np.asarray(y_true).astype(bool)
    n_pos, n_neg = y.sum(), (~y).sum()
    if n_pos == 0 or n_neg == 0:
        raise ValueError("AUC needs both classes")
    ranks = rankdata(score)
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


_FACTOR_LABELS = {
    "age_band": "age",
    "appointment_type": "type",
    "contact_mode": "mode",
    "weekday": "day",
    "specialty": "specialty",
    "prior_dnas": "prior DNAs",
}
_NUMERIC_LABELS = {
    "np.log1p(lead_days)": "log(1 + lead days)",
    "imd_c": "IMD decile (per step up, 1 = most deprived)",
    "imd_missing": "IMD missing",
    "distance_km": "distance (per km)",
    "has_mobile": "has mobile number",
}
_TERM = re.compile(r"^C\((?P<var>\w+)(?:, Treatment\('[^']*'\))?\)\[T\.(?P<level>.+)\]$")


def _pretty(term: str) -> str:
    m = _TERM.match(term)
    if m:
        return f"{_FACTOR_LABELS.get(m['var'], m['var'])}: {m['level']}"
    return _NUMERIC_LABELS.get(term, term)


def fit(df: pd.DataFrame) -> ModelResult:
    d = prepare(df)
    train, test = (
        d[d["appointment_datetime"] < SPLIT_DATE],
        d[d["appointment_datetime"] >= SPLIT_DATE],
    )
    model = smf.logit(FORMULA, data=train).fit(disp=False, maxiter=100)
    conf = model.conf_int()
    ors = pd.DataFrame(
        {
            "term": [_pretty(t) for t in model.params.index],
            "odds_ratio": np.exp(model.params.values),
            "ci_low": np.exp(conf[0].values),
            "ci_high": np.exp(conf[1].values),
            "p_value": model.pvalues.values,
        }
    )
    ors = ors[ors["term"] != "Intercept"].reset_index(drop=True)
    p_train = model.predict(train)
    p_test = model.predict(test)
    scored = test.assign(risk=p_test.values)
    scored["decile"] = pd.qcut(scored["risk"].rank(method="first"), 10, labels=False) + 1
    calib = (
        scored.groupby("decile")
        .agg(
            predicted=("risk", "mean"),
            observed=("dna", "mean"),
            n=("dna", "size"),
            dnas=("dna", "sum"),
        )
        .reset_index()
    )
    top = calib.loc[calib["decile"] == 10, "dnas"].iloc[0] / calib["dnas"].sum()
    return ModelResult(
        odds_ratios=ors,
        auc_train=auc(train["dna"].to_numpy(), p_train.to_numpy()),
        auc_test=auc(test["dna"].to_numpy(), p_test.to_numpy()),
        brier_test=float(np.mean((p_test.to_numpy() - test["dna"].to_numpy()) ** 2)),
        base_rate_test=float(test["dna"].mean()),
        calibration=calib,
        top_decile_capture=float(top),
        n_train=len(train),
        n_test=len(test),
        test_scored=scored,
    )
