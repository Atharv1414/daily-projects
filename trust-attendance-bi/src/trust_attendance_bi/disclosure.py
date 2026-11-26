"""Statistical disclosure control for published tables, in the style of DfE statistics.

A rate for three pupils with SEN in one year group of one school can identify a child. Before
any table leaves the mart:

1. **Primary suppression:** any row describing fewer than ``threshold`` pupils (but more
   than zero) has its numbers replaced by ``c`` (confidential).
2. **Secondary suppression:** if a group of sibling rows (rows that share every dimension but
   one, and therefore add up to a published total) contains exactly one suppressed row, the
   next-smallest row in that group is suppressed too, so the hidden one cannot be worked out
   by subtraction. This repeats until nothing changes, because one secondary suppression can
   expose another group.
3. **Rounding** (optional): head counts are rounded to the nearest 5.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

SUPPRESSED = "c"


def suppress(
    df: pd.DataFrame,
    dims: Sequence[str],
    count_col: str = "pupils",
    threshold: int = 5,
) -> pd.DataFrame:
    """Returns a copy with a boolean ``suppressed`` column and hidden values set to ``c``."""
    if count_col not in df.columns:
        raise ValueError(f"suppression needs a '{count_col}' column")
    out = df.copy()
    counts = out[count_col].fillna(0).astype(int)
    hidden = (counts > 0) & (counts < threshold)

    changed = True
    while changed and len(dims) > 0:
        changed = False
        for free in dims:
            others = [d for d in dims if d != free]
            groups = (
                out.groupby(others, dropna=False, sort=False).groups if others else {(): out.index}
            )
            for index in groups.values():
                members = list(index)
                if len(members) < 2:
                    continue
                n_hidden = int(hidden[members].sum())
                if n_hidden == 1:
                    # Prefer a real group; if only zeros are left, hide a zero, since the
                    # hidden value would otherwise equal the published total.
                    candidates = [m for m in members if not hidden[m] and counts[m] > 0] or [
                        m for m in members if not hidden[m]
                    ]
                    victim = min(candidates, key=lambda m: (counts[m], str(m)))
                    hidden[victim] = True
                    changed = True

    value_cols = [c for c in out.columns if c not in dims]
    out[value_cols] = out[value_cols].astype(object)
    out.loc[hidden, value_cols] = SUPPRESSED
    out["suppressed"] = hidden
    return out


def round_counts(values: pd.Series, base: int = 5) -> pd.Series:
    """Rounds published head counts to the nearest ``base`` (half up), leaving ``c`` alone."""

    def _round(v):
        if v == SUPPRESSED or pd.isna(v):
            return v
        return int(base * ((int(v) + base // 2) // base))

    return values.map(_round)
