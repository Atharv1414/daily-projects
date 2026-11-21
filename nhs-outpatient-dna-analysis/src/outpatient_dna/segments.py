"""DNA rates by segment with Wilson confidence intervals."""

from __future__ import annotations

import pandas as pd

from outpatient_dna.stats import wilson_ci


def rate_table(df: pd.DataFrame, by: str | list[str], min_n: int = 0) -> pd.DataFrame:
    """DNA rate per group with 95% Wilson CI, sorted by the group order."""
    g = df.groupby(by, observed=True)["dna"].agg(["sum", "count"]).reset_index()
    g = g.rename(columns={"sum": "dnas", "count": "appointments"})
    g = g[g["appointments"] >= min_n]
    cis = [wilson_ci(int(x), int(n)) for x, n in zip(g["dnas"], g["appointments"], strict=True)]
    g["dna_rate"] = g["dnas"] / g["appointments"]
    g["ci_low"] = [c[0] for c in cis]
    g["ci_high"] = [c[1] for c in cis]
    return g.reset_index(drop=True)


def high_risk_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Deep dive: combinations of age, deprivation and lead time, ranked by DNA rate."""
    d = df.copy()
    d["young"] = d["age_band"].isin(["18-29", "30-44"])
    d["deprived"] = d["imd_group"].isin(["1", "2", "3"])
    d["long_wait"] = d["lead_days"] >= 56
    d["prior_dna"] = d["prior_dnas"] > 0
    t = rate_table(d, ["young", "deprived", "long_wait", "prior_dna"])
    t["share_of_dnas"] = t["dnas"] / t["dnas"].sum()
    return t.sort_values("dna_rate", ascending=False).reset_index(drop=True)


def specialty_imd_matrix(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["imd_group"] != "Unknown"].copy()
    d["imd_quintile"] = ((d["imd_decile"] + 1) // 2).astype(int)
    return d.pivot_table(
        index="specialty", columns="imd_quintile", values="dna", aggfunc="mean", observed=True
    )
