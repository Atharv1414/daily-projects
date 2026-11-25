"""Raw tables in, one tidy row per mortgage out, with a count for every rule that fired."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mortgage_exits.config import Study
from mortgage_exits.datagen import SVR_MARGIN, RawData, monthly_payment

CODES = {
    "PRODUCT_TRANSFER": 1,
    "REDEMPTION:REMORTGAGE": 2,
    "REDEMPTION:SALE": 3,
    "REDEMPTION:REPAID": 3,
    "ARREARS_90": 4,
}


class DataContractError(ValueError):
    """The extract does not have the shape the study needs."""


@dataclass
class CleaningLog:
    rows: list[tuple[str, int]] = field(default_factory=list)

    def add(self, rule: str, count: int) -> None:
        self.rows.append((rule, int(count)))

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=["rule", "rows"])


def parse_ltv(values: pd.Series) -> pd.Series:
    """Accepts 75, "75.0", "75.0%" and 0.75. Small numbers are shares."""
    text = values.astype("string").str.strip().str.rstrip("%")
    number = pd.to_numeric(text, errors="coerce").astype(float)
    number = number.where(number > 1.5, number * 100)
    return number.where(number.between(1, 120))


def parse_dates(values: pd.Series) -> pd.Series:
    """ISO dates, or UK dates with slashes. Anything else becomes missing rather than a guess."""
    text = values.astype("string")
    iso = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    uk = pd.to_datetime(text, format="%d/%m/%Y", errors="coerce")
    return iso.fillna(uk)


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise DataContractError(f"{name} is missing {', '.join(sorted(missing))}.")


def clean_rates(rates: pd.DataFrame, log: CleaningLog) -> pd.Series:
    _require(rates, {"month", "rate"}, "rates")
    series = rates.set_index(pd.to_datetime(rates["month"]))["rate"].sort_index()
    log.add("Market rate missing for a month: interpolated", series.isna().sum())
    return series.interpolate()


def clean_accounts(accounts: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    _require(
        accounts,
        {
            "account_id",
            "fix_end",
            "fixed_rate",
            "balance",
            "ltv",
            "age",
            "years_left",
            "channel",
            "region",
            "acquired_on",
            "fix_years",
        },
        "accounts",
    )
    out = accounts.drop_duplicates()
    log.add("Account row repeated: dropped", len(accounts) - len(out))
    if out["account_id"].duplicated().any():
        raise DataContractError("Two different rows share an account number.")
    out = out.copy()
    out["fix_end"] = parse_dates(out["fix_end"])
    log.add("Fix end date unreadable: dropped", out["fix_end"].isna().sum())
    out = out.dropna(subset=["fix_end"])
    out["acquired_on"] = parse_dates(out["acquired_on"])
    text = out["ltv"].astype("string")
    out["ltv"] = parse_ltv(out["ltv"])
    log.add(
        "LTV written as a percentage or a share: converted",
        (
            text.str.endswith("%") | (pd.to_numeric(text.str.rstrip("%"), errors="coerce") <= 1.5)
        ).sum(),
    )
    log.add("LTV missing: set to the median for the channel", out["ltv"].isna().sum())
    out["ltv"] = out["ltv"].fillna(out.groupby("channel")["ltv"].transform("median"))
    pence = out["balance"] > 1_200_000
    log.add("Balance recorded in pence: divided by 100", pence.sum())
    out.loc[pence, "balance"] = out.loc[pence, "balance"] / 100
    odd = ~out["age"].between(18, 100)
    log.add("Age missing or impossible: set to the median", odd.sum())
    out.loc[odd, "age"] = out.loc[~odd, "age"].median()
    tidy = out["region"].str.strip().str.title()
    log.add("Region spelling: tidied", (tidy != out["region"]).sum())
    out["region"] = tidy
    return out


def first_events(events: pd.DataFrame, known: pd.Series, study: Study, log: CleaningLog):
    """The first completed event for each mortgage. Later ones come from systems that lag."""
    _require(events, {"account_id", "event_date", "code", "status"}, "events")
    out = events.drop_duplicates()
    log.add("Event repeated in the feed: dropped", len(events) - len(out))
    cancelled = out["status"] != "COMPLETED"
    log.add("Application cancelled, so nothing happened: dropped", cancelled.sum())
    out = out[~cancelled].copy()
    orphan = ~out["account_id"].isin(known)
    log.add("Event for an unknown account: dropped", orphan.sum())
    out = out[~orphan]
    out["cause"] = out["code"].map(CODES)
    if out["cause"].isna().any():
        raise DataContractError(
            f"Unknown event code {out.loc[out['cause'].isna(), 'code'].iloc[0]}."
        )
    out["event_date"] = parse_dates(out["event_date"])
    out = out[out["event_date"] <= study.extract].sort_values(["event_date", "cause"])
    first = out.drop_duplicates("account_id", keep="first")
    log.add("Event after the mortgage had already gone: dropped", len(out) - len(first))
    return first[["account_id", "event_date", "cause"]]


def months_between(start: pd.Series, end: pd.Series) -> pd.Series:
    """Which month of the clock a date falls in: 1 is the first month after the start."""
    whole = (end.dt.year - start.dt.year) * 12 + end.dt.month - start.dt.month
    return whole + 1


def build_study(raw: RawData, study: Study) -> tuple[pd.DataFrame, pd.Series, CleaningLog]:
    log = CleaningLog()
    rates = clean_rates(raw.rates, log)
    accounts = clean_accounts(raw.accounts, log)
    events = first_events(raw.events, accounts["account_id"], study, log)
    out = accounts.merge(events, on="account_id", how="left")
    out["start"] = out["fix_end"] - pd.DateOffset(months=study.lead_months)

    # Last whole month in which a mortgage could have been seen to leave.
    seen = months_between(out["start"], pd.Series(study.extract, index=out.index))
    limit = np.minimum(seen, study.max_month)
    event_month = months_between(out["start"], out["event_date"])
    happened = out["cause"].notna() & (event_month <= limit)
    out["cause"] = np.where(happened, out["cause"], 0).astype(int)
    out["exit"] = np.where(happened, event_month, limit).astype(int)
    out["entry"] = (
        (months_between(out["start"], out["acquired_on"]) - 1).fillna(0).clip(lower=0).astype(int)
    )
    unseen = out["exit"] <= out["entry"]
    log.add("Never at risk while we could see it: dropped", unseen.sum())
    out = out[~unseen].reset_index(drop=True)

    market = out["start"].map(rates).astype(float)
    out["start_rate"] = market
    out["shock"] = (
        monthly_payment(out["balance"], market, out["years_left"])
        / monthly_payment(out["balance"], out["fixed_rate"], out["years_left"])
        - 1
    )
    out["broker"] = (out["channel"] == "Broker").astype(float)
    out["ltv10"] = (out["ltv"] - 65) / 10
    out["older"] = (out["age"] > 50).astype(float)
    out["shock_group"] = pd.cut(
        out["shock"],
        [-np.inf, 0.0, 0.2, 0.4, np.inf],
        labels=["Lower or same", "Up to 20% more", "20-40% more", "Over 40% more"],
    )
    log.add("Mortgages in the study", len(out))
    return out, rates, log


__all__ = ["SVR_MARGIN", "CleaningLog", "DataContractError", "build_study"]
