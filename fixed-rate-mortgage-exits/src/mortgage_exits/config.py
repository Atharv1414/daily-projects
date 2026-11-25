"""Study design and business assumptions, in one place."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import pandas as pd

# The ways a mortgage can leave the "fix ending" state. 0 means still there when last seen.
CAUSES: dict[int, str] = {1: "transferred", 2: "left", 3: "redeemed", 4: "arrears"}
LABELS: dict[int, str] = {
    1: "Took a new deal with us",
    2: "Remortgaged elsewhere",
    3: "Sold or repaid",
    4: "Fell into arrears",
}
LEFT = 2


@dataclass(frozen=True)
class Study:
    """The clock starts six months before the fix ends, when customers may lock in a new rate."""

    accounts: int = 45_000
    seed: int = 20261125
    lead_months: int = 6
    max_month: int = 24
    extract: pd.Timestamp = field(default_factory=lambda: pd.Timestamp("2026-09-30"))
    split: pd.Timestamp = field(default_factory=lambda: pd.Timestamp("2025-04-01"))
    horizon: int = 12
    bootstrap: int = 200

    def __post_init__(self) -> None:
        if self.accounts < 200:
            raise ValueError("The study needs at least 200 accounts.")
        if not 0 < self.horizon <= self.max_month:
            raise ValueError("The horizon must fall inside the follow-up period.")
        if self.split >= self.extract:
            raise ValueError("The split must be before the extract date.")

    @classmethod
    def from_env(cls) -> Study:
        """`MORTGAGE_ACCOUNTS` and `MORTGAGE_SEED` override the defaults."""
        return cls(
            accounts=int(os.environ.get("MORTGAGE_ACCOUNTS", cls.accounts)),
            seed=int(os.environ.get("MORTGAGE_SEED", cls.seed)),
        )


@dataclass(frozen=True)
class Economics:
    """Planning assumptions, not findings. The report shows how the answer moves with them."""

    net_margin: float = 0.0105  # yearly, on the balance kept
    kept_years: float = 2.0
    call_cost: float = 22.0
    save_rate: float = 0.06  # of people who would have left and are called

    def __post_init__(self) -> None:
        if not 0 <= self.save_rate <= 1:
            raise ValueError("save_rate is a share between 0 and 1.")

    def value_if_saved(self, balance: pd.Series) -> pd.Series:
        return balance * self.net_margin * self.kept_years
