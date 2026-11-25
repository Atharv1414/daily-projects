"""From forecast to plan: who is worth calling, and how sure do we need to be?"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mortgage_exits.config import Economics


def plan(predictions: pd.DataFrame, economics: Economics) -> pd.DataFrame:
    """Expected value of calling each customer, best first."""
    out = predictions.copy()
    out["saved_value"] = economics.value_if_saved(out["balance"])
    out["expected"] = out["p"] * economics.save_rate * out["saved_value"] - economics.call_cost
    return out.sort_values("expected", ascending=False).reset_index(drop=True)


def gains(predictions: pd.DataFrame, economics: Economics) -> pd.DataFrame:
    """Margin at risk reached by calling the top share, ranked three ways. Uses real outcomes."""
    frame = predictions.assign(
        at_risk=predictions["y"]
        * predictions["w"]
        * economics.value_if_saved(predictions["balance"]),
        by_value=predictions["p"] * predictions["balance"],
    )
    total = frame["at_risk"].sum()
    share = np.linspace(0, 1, 21)
    rows = []
    for name, column in [
        ("Chance x balance", "by_value"),
        ("Chance only", "p"),
        ("Balance only", "balance"),
    ]:
        ranked = frame.sort_values(column, ascending=False)["at_risk"].cumsum().to_numpy()
        for s in share:
            reached = 0.0 if s == 0 else ranked[int(np.ceil(s * len(frame))) - 1] / total
            rows.append({"ranking": name, "share": s, "reached": reached})
    return pd.DataFrame(rows)


def break_even(predictions: pd.DataFrame, economics: Economics, tenths: int = 10) -> pd.DataFrame:
    """The save rate at which calling each tenth of customers pays for itself, on real outcomes."""
    frame = predictions.assign(rank_value=predictions["p"] * predictions["balance"])
    frame["tenth"] = (
        pd.qcut(frame["rank_value"].rank(method="first", ascending=False), tenths, labels=False) + 1
    )
    frame["loss"] = frame["y"] * frame["w"] * economics.value_if_saved(frame["balance"])
    grouped = frame.groupby("tenth")
    out = pd.DataFrame(
        {
            "accounts": grouped.size(),
            "left_share": grouped["y"].apply(
                lambda s: np.average(s, weights=frame.loc[s.index, "w"])
            ),
            "margin_lost": grouped["loss"].sum() / grouped["w"].sum(),
        }
    ).reset_index()
    out["break_even_save_rate"] = economics.call_cost / out["margin_lost"]
    out["net_per_call"] = out["margin_lost"] * economics.save_rate - economics.call_cost
    return out


def sensitivity(predictions: pd.DataFrame, economics: Economics) -> pd.DataFrame:
    """Net value of the plan's calls, and of calling everybody, as the save rate moves."""
    rows = []
    for rate in (0.01, 0.02, 0.04, 0.06, 0.10):
        e = Economics(economics.net_margin, economics.kept_years, economics.call_cost, rate)
        ranked = plan(predictions, e)
        chosen = ranked[ranked["expected"] > 0]
        real = (chosen["y"] * chosen["w"] * chosen["saved_value"] * rate).sum()
        everyone = (ranked["y"] * ranked["w"] * ranked["saved_value"] * rate).sum()
        rows.append(
            {
                "save_rate": rate,
                "calls": len(chosen),
                "net_plan": real - len(chosen) * e.call_cost,
                "net_everyone": everyone - len(ranked) * e.call_cost,
            }
        )
    return pd.DataFrame(rows)
