"""Non-parametric estimators, written out: Kaplan-Meier and Aalen-Johansen with delayed entry."""

from __future__ import annotations

import numpy as np
import pandas as pd


def risk_table(
    entry: np.ndarray, exit_: np.ndarray, cause: np.ndarray, months: int, causes: tuple[int, ...]
) -> tuple[np.ndarray, np.ndarray]:
    """How many are at risk in each month, and how many leave for each cause.

    A mortgage is at risk in month t when entry < t <= exit. Those bought part-way through only
    join the risk set once they can be seen; counting them earlier would credit them with months
    in which they could not have left.
    """
    entry, exit_, cause = (np.asarray(a, dtype=int) for a in (entry, exit_, cause))
    if np.any(exit_ <= entry):
        raise ValueError("Every mortgage must be at risk for at least one month.")
    joined = np.bincount(np.minimum(entry, months), minlength=months + 1)
    ended = np.bincount(np.minimum(exit_, months + 1), minlength=months + 2)
    at_risk = np.cumsum(joined)[:months] - np.concatenate([[0], np.cumsum(ended)[1:months]])
    inside = exit_ <= months
    d = np.array(
        [
            np.bincount(exit_[inside & (cause == k)], minlength=months + 1)[1 : months + 1]
            for k in causes
        ]
    )
    return at_risk.astype(float), d.astype(float)


def _divide(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.divide(a, b, out=np.zeros_like(a, dtype=float), where=b > 0)


def kaplan_meier(entry, exit_, event, months: int) -> np.ndarray:
    """Probability of no event by the end of each month (months 1..n)."""
    at_risk, d = risk_table(entry, exit_, np.asarray(event, dtype=int), months, (1,))
    return np.cumprod(1 - _divide(d[0], at_risk))


def aalen_johansen(entry, exit_, cause, months: int, causes: tuple[int, ...] = (1, 2, 3, 4)):
    """Cumulative incidence of each cause, with standard errors, as a tidy frame."""
    n, d = risk_table(entry, exit_, cause, months, causes)
    hazard = _divide(d, n[None, :])
    survival = np.cumprod(1 - hazard.sum(axis=0))
    before = np.concatenate([[1.0], survival[:-1]])
    cif = np.cumsum(before * hazard, axis=1)
    frames = []
    for i, k in enumerate(causes):
        se = np.sqrt(_variance(n, d.sum(axis=0), d[i], before, cif[i]))
        frames.append(
            pd.DataFrame(
                {
                    "cause": k,
                    "month": np.arange(1, months + 1),
                    "cif": cif[i],
                    "se": se,
                    "at_risk": n,
                }
            )
        )
    out = pd.concat(frames, ignore_index=True)
    # Intervals on the log-log scale stay between 0 and 1.
    inner = np.clip(out["cif"], 1e-12, 1 - 1e-12)
    width = 1.96 * out["se"] / (inner * np.abs(np.log(inner)))
    out["low"] = np.where(out["cif"] > 0, inner ** np.exp(width), 0.0)
    out["high"] = np.where(out["cif"] > 0, inner ** np.exp(-width), 0.0)
    return out


def _variance(n, d_all, d_k, before, cif) -> np.ndarray:
    """Aalen's variance, by Greenwood-type sums over the months so far."""
    out = np.zeros(len(n))
    for t in range(len(n)):
        m, s = n[: t + 1], before[: t + 1]
        gap = cif[t] - cif[: t + 1]
        a = _divide(d_all[: t + 1], m * np.maximum(m - d_all[: t + 1], 1)) * gap**2
        b = _divide(d_k[: t + 1] * (m - d_k[: t + 1]), m**3) * s**2
        c = _divide(d_k[: t + 1], m**2) * s * gap
        out[t] = max((a + b - 2 * c).sum(), 0.0)
    return out


def naive_one_minus_km(entry, exit_, cause, months: int, k: int) -> np.ndarray:
    """The common mistake: treat every other way of leaving as if it were missing data."""
    return 1 - kaplan_meier(entry, exit_, np.asarray(cause) == k, months)


def cif_at(frame: pd.DataFrame, cause: int, month: int) -> pd.Series:
    row = frame[(frame["cause"] == cause) & (frame["month"] == month)]
    if row.empty:
        raise KeyError(f"No estimate for cause {cause} at month {month}.")
    return row.iloc[0]


def bootstrap_difference(
    data: pd.DataFrame, mask_a, mask_b, cause: int, month: int, reps: int, seed: int = 0
) -> tuple[float, float, float]:
    """Difference in cumulative incidence between two groups, with a percentile interval."""
    rng = np.random.default_rng(seed)
    arrays = []
    for mask in (mask_a, mask_b):
        part = data[mask]
        if part.empty:
            raise ValueError("A group is empty.")
        arrays.append(part[["entry", "exit", "cause"]].to_numpy())

    def value(a: np.ndarray) -> float:
        n, d = risk_table(a[:, 0], a[:, 1], a[:, 2], month, (1, 2, 3, 4))
        h = _divide(d, n[None, :])
        s = np.concatenate([[1.0], np.cumprod(1 - h.sum(axis=0))[:-1]])
        return float((s * h[cause - 1]).sum())

    point = value(arrays[0]) - value(arrays[1])
    draws = [
        value(arrays[0][rng.integers(0, len(arrays[0]), len(arrays[0]))])
        - value(arrays[1][rng.integers(0, len(arrays[1]), len(arrays[1]))])
        for _ in range(reps)
    ]
    low, high = np.percentile(draws, [2.5, 97.5])
    return point, float(low), float(high)
