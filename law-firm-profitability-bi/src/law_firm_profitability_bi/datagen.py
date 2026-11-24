"""Seeded source extracts for a fictional UK law firm, "Hartwell Pryce LLP".

The shape follows a practice-management system: versioned time entries (a correction is a new
version, never an update), bills, receipts and effective-dated rate cards. Known problems are
injected on purpose: duplicate exports, unknown timekeepers, impossible hours, late posting,
matter transfers and voided time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .config import CUTOFF, FIRST_MONTH

# (id, parent, name). Ragged on purpose: Private Client has no teams and Arbitration sits
# directly under its division.
ORG = [
    ("FIRM", None, "Hartwell Pryce LLP"),
    ("BUS", "FIRM", "Business Services"),
    ("DIS", "FIRM", "Disputes"),
    ("IND", "FIRM", "Individuals"),
    ("CORP", "BUS", "Corporate"),
    ("REAL", "BUS", "Real Estate"),
    ("EMP", "BUS", "Employment"),
    ("LIT", "DIS", "Litigation"),
    ("ARB", "DIS", "Arbitration"),
    ("PC", "IND", "Private Client"),
    ("CORP-MA", "CORP", "M&A"),
    ("CORP-BK", "CORP", "Banking"),
    ("REAL-DEV", "REAL", "Development"),
    ("REAL-INV", "REAL", "Investment"),
    ("LIT-COM", "LIT", "Commercial Litigation"),
    ("LIT-CON", "LIT", "Construction"),
]
# Leaf unit -> (share of matters, hours per matter-month, fee pressure, late-posting rate)
LEAVES = {
    "CORP-MA": (0.12, 30.0, 0.02, 0.03),
    "CORP-BK": (0.10, 26.0, 0.02, 0.03),
    "REAL-DEV": (0.12, 22.0, 0.03, 0.04),
    "REAL-INV": (0.11, 20.0, 0.03, 0.04),
    "EMP": (0.14, 15.0, 0.04, 0.16),
    "LIT-COM": (0.13, 27.0, 0.05, 0.05),
    "LIT-CON": (0.08, 30.0, 0.13, 0.06),
    "ARB": (0.05, 34.0, 0.04, 0.04),
    "PC": (0.15, 10.0, 0.06, 0.05),
}
GRADES = ["Partner", "Legal Director", "Senior Associate", "Associate", "Trainee", "Paralegal"]
BASE_RATE = dict(zip(GRADES, [560, 440, 360, 275, 150, 125], strict=True))
COST_SHARE = dict(zip(GRADES, [0.46, 0.44, 0.40, 0.38, 0.42, 0.45], strict=True))
GRADE_MIX = [0.18, 0.10, 0.22, 0.28, 0.10, 0.12]
OFFICES = {"London": 1.30, "Manchester": 1.0, "Leeds": 0.95, "Bristol": 1.0}


@dataclass(frozen=True)
class GenConfig:
    seed: int = 2026
    clients: int = 260
    matters: int = 1500
    timekeepers: int = 150
    entries: int = 220_000


def _dates(days: np.ndarray, origin: date) -> pd.Series:
    return pd.Series(pd.Timestamp(origin) + pd.to_timedelta(days.astype("int64"), unit="D"))


def _timekeepers(cfg: GenConfig, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns timekeepers and an effective-dated rate card with promotions and May uplifts."""
    leaves = list(LEAVES)
    people, rates = [], []
    for i in range(cfg.timekeepers):
        tk = f"TK{i + 1:03d}"
        office = rng.choice(list(OFFICES), p=[0.4, 0.25, 0.2, 0.15])
        # Cover every leaf and grade before drawing at random.
        unit = leaves[i % len(leaves)] if i < 54 else rng.choice(leaves)
        grade = GRADES[(i // len(leaves)) % 6] if i < 54 else rng.choice(GRADES, p=GRADE_MIX)
        people.append((tk, f"Fee earner {i + 1:03d}", office, unit))
        rate = BASE_RATE[grade] * OFFICES[office] * rng.uniform(0.93, 1.07)
        for k, start in enumerate([date(2024, 5, 1), date(2025, 5, 1), date(2026, 5, 1)]):
            if k:
                rate *= 1.045
                level = GRADES.index(grade)
                if 1 <= level <= 3 and rng.random() < 0.09:
                    promoted = GRADES[level - 1]
                    rate *= 1 + 0.5 * (BASE_RATE[promoted] / BASE_RATE[grade] - 1)
                    grade = promoted
            rates.append((tk, start, grade, round(rate), round(rate * COST_SHARE[grade], 2)))
    columns = ["timekeeper_id", "effective_from", "grade", "standard_rate", "cost_rate"]
    return (
        pd.DataFrame(people, columns=["timekeeper_id", "name", "office", "unit_id"]),
        pd.DataFrame(rates, columns=columns),
    )


def _matters(
    cfg: GenConfig, rng: np.random.Generator
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sectors = ["Retail", "Energy", "Technology", "Property", "Public sector", "Private individual"]
    clients = pd.DataFrame(
        {
            "client_id": [f"C{i + 1:04d}" for i in range(cfg.clients)],
            "client_name": [f"Client {i + 1:04d}" for i in range(cfg.clients)],
            "sector": rng.choice(sectors, cfg.clients, p=[0.18, 0.12, 0.2, 0.22, 0.1, 0.18]),
            "payment_days": rng.gamma(6.0, 7.0, cfg.clients).round().astype(int) + 8,
        }
    )
    weights = rng.pareto(1.6, cfg.clients) + 0.2
    share = np.array([v[0] for v in LEAVES.values()])
    horizon = (CUTOFF - FIRST_MONTH).days
    opened = np.sort(rng.integers(-120, horizon - 5, cfg.matters))
    length = rng.gamma(2.2, 110, cfg.matters).astype(int) + 20
    closed = opened + length
    matters = pd.DataFrame(
        {
            "matter_id": [f"M{i + 1:05d}" for i in range(cfg.matters)],
            "client_id": rng.choice(clients.client_id, cfg.matters, p=weights / weights.sum()),
            "unit_id": rng.choice(list(LEAVES), cfg.matters, p=share / share.sum()),
            "opened_date": _dates(opened, FIRST_MONTH),
            "closed_date": _dates(closed, FIRST_MONTH).where(closed <= horizon),
            "discount_pct": rng.choice(
                [0.0, 0.05, 0.10, 0.15, 0.20], cfg.matters, p=[0.3, 0.25, 0.25, 0.13, 0.07]
            ),
            "billing_months": rng.choice([1, 2, 3], cfg.matters, p=[0.55, 0.2, 0.25]),
        }
    )
    # New instructions are won on deeper discounts each year: the story behind rate leakage.
    drift = 0.04 * np.clip(opened / horizon, 0, 1)
    matters["discount_pct"] = (matters.discount_pct + drift).round(3)
    walled = rng.choice(matters.matter_id, 24, replace=False)
    walls = pd.DataFrame(
        [(m, u) for m in sorted(walled) for u in ("finance", "mp")],
        columns=["matter_id", "user_id"],
    )
    return clients, matters, walls


def _time(
    cfg: GenConfig, rng: np.random.Generator, people: pd.DataFrame, matters: pd.DataFrame
) -> pd.DataFrame:
    horizon = (CUTOFF - FIRST_MONTH).days
    opened = (matters.opened_date - pd.Timestamp(FIRST_MONTH)).dt.days.to_numpy()
    closed = (matters.closed_date - pd.Timestamp(FIRST_MONTH)).dt.days.fillna(horizon).to_numpy(int)
    start, end = np.maximum(opened, 0), np.minimum(closed, horizon)
    live = np.maximum(end - start, 1)
    intensity = matters.unit_id.map(lambda u: LEAVES[u][1]).to_numpy()
    weight = live * intensity * rng.gamma(1.5, 1.0, len(matters)) * (end > start)
    n = cfg.entries
    m = np.sort(rng.choice(len(matters), n, p=weight / weight.sum()))
    work = start[m] + (rng.random(n) * live[m]).astype(int)
    weekday = (pd.Timestamp(FIRST_MONTH).weekday() + work) % 7
    work = np.where(weekday >= 5, np.maximum(work - (weekday - 4), start[m]), work)

    unit_of = matters.unit_id.to_numpy()[m]
    timekeeper = np.empty(n, dtype=object)
    for unit in LEAVES:
        ids = people.loc[people.unit_id == unit, "timekeeper_id"].to_numpy()
        rows = np.flatnonzero(unit_of == unit)
        timekeeper[rows] = rng.choice(ids, len(rows))
    hours = np.clip((rng.gamma(2.0, 0.55, n) * 10).round(), 1, 110) / 10

    late_rate = np.array([LEAVES[u][3] for u in unit_of])
    late = rng.random(n) < late_rate
    lag = np.where(late, rng.integers(12, 60, n), rng.integers(0, 4, n))
    frame = pd.DataFrame(
        {
            "entry_id": np.arange(1, n + 1),
            "version": 1,
            "work_day": work,
            "posted_day": work + lag,
            "timekeeper_id": timekeeper,
            "matter_id": matters.matter_id.to_numpy()[m],
            "hours": hours,
            "status": "active",
        }
    )
    # Corrections: a second version posted 3-45 days later.
    kind = rng.choice(["none", "hours", "transfer", "void"], n, p=[0.955, 0.022, 0.015, 0.008])
    fixes = frame[kind != "none"].copy()
    fix_kind = kind[kind != "none"]
    fixes["version"] = 2
    fixes["posted_day"] += rng.integers(3, 46, len(fixes))
    changed = np.round(fixes.hours * rng.uniform(0.4, 1.3, len(fixes)), 1)
    fixes["hours"] = np.where(fix_kind == "hours", np.maximum(changed, 0.1), fixes.hours)
    fixes.loc[fix_kind == "void", "status"] = "void"
    moved = np.flatnonzero(fix_kind == "transfer")
    fixes.iloc[moved, fixes.columns.get_loc("matter_id")] = rng.choice(
        matters.matter_id[(opened < 0).nonzero()[0]], len(moved)
    )
    frame = pd.concat([frame, fixes], ignore_index=True)
    frame = frame[frame.posted_day <= horizon]
    frame["work_date"] = _dates(frame.work_day.to_numpy(), FIRST_MONTH).to_numpy()
    frame["posted_at"] = _dates(frame.posted_day.to_numpy(), FIRST_MONTH).to_numpy()
    return frame.drop(columns=["work_day", "posted_day"])


def _bill(
    rng: np.random.Generator,
    time: pd.DataFrame,
    matters: pd.DataFrame,
    clients: pd.DataFrame,
    rates: pd.DataFrame,
    people: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bills each surviving entry on its matter's next bill date, then collects the cash."""
    final = time.sort_values(["entry_id", "version"]).drop_duplicates("entry_id", keep="last")
    final = final[final.status == "active"].merge(matters, on="matter_id")
    month = final.posted_at.dt.year * 12 + final.posted_at.dt.month - 1
    due = month + final.billing_months - (month % final.billing_months)
    final["bill_date"] = pd.to_datetime(
        {"year": due // 12, "month": due % 12 + 1, "day": 1}
    ) + pd.Timedelta(days=5)
    final = final[final.bill_date <= pd.Timestamp(CUTOFF)].copy()

    card = rates.assign(
        effective_from=pd.to_datetime(rates.effective_from).astype("datetime64[ns]")
    )
    final["work_date"] = final.work_date.astype("datetime64[ns]")
    final = pd.merge_asof(
        final.sort_values("work_date"),
        card.sort_values("effective_from"),
        left_on="work_date",
        right_on="effective_from",
        by="timekeeper_id",
    )
    value = (final.hours * (final.standard_rate * (1 - final.discount_pct)).round(2)).round(2)
    pressure = final.unit_id.map(lambda u: LEAVES[u][2]).to_numpy()
    year_two = (final.bill_date >= pd.Timestamp("2025-11-01")).to_numpy()
    pressure = np.where((final.unit_id == "LIT-CON") & year_two, pressure + 0.07, pressure)
    cut = rng.random(len(final)) < pressure * 2
    write_down = np.where(cut, rng.uniform(0.2, 0.8, len(final)), 0.0)
    write_down = np.where(rng.random(len(final)) < pressure * 0.15, 1.0, write_down)
    final["billed_amount"] = (value * (1 - write_down)).round(2)
    final = final.sort_values(["matter_id", "bill_date", "entry_id"])
    final["bill_id"] = "B" + (final.groupby(["matter_id", "bill_date"]).ngroup() + 1).astype(
        str
    ).str.zfill(6)
    lines = final[["bill_id", "bill_date", "matter_id", "entry_id", "billed_amount"]]

    bills = lines.groupby(["bill_id", "bill_date", "matter_id"], as_index=False).agg(
        amount=("billed_amount", "sum")
    )
    bills = bills.merge(matters[["matter_id", "client_id"]]).merge(clients)
    bills["amount"] = bills.amount.round(2)
    n = len(bills)
    outcome = rng.choice(["full", "partial", "bad"], n, p=[0.90, 0.07, 0.03])
    lag = np.maximum((bills.payment_days * rng.lognormal(0, 0.35, n)).round(), 1).astype(int)
    paid = (bills.amount * np.where(outcome == "full", 1.0, rng.uniform(0.3, 0.9, n))).round(2)
    paid = paid.where(outcome != "bad", 0.0)
    cash = pd.DataFrame(
        {
            "bill_id": bills.bill_id,
            "receipt_date": bills.bill_date + pd.to_timedelta(lag, unit="D"),
            "amount": paid,
            "kind": "cash",
        }
    )
    rest = cash.assign(
        amount=(bills.amount - paid).round(2),
        receipt_date=cash.receipt_date + pd.Timedelta(days=120),
        kind="bad_debt",
    )
    receipts = pd.concat([cash, rest])
    receipts = receipts[
        (receipts.amount > 0) & (receipts.receipt_date <= pd.Timestamp(CUTOFF))
    ].sort_values(["receipt_date", "bill_id"])
    receipts.insert(0, "receipt_id", np.arange(1, len(receipts) + 1))
    return lines, receipts


def _add_mess(rng: np.random.Generator, time: pd.DataFrame) -> pd.DataFrame:
    n = len(time)
    duplicates = time.iloc[rng.choice(n, n // 120, replace=False)]
    bad = time.iloc[rng.choice(n, max(8, n // 800), replace=False)].copy()
    bad["entry_id"] = np.arange(len(bad)) + 10_000_000
    bad["version"] = 1
    bad["status"] = "active"
    problem = np.arange(len(bad)) % 4
    bad.loc[problem == 0, "timekeeper_id"] = "TK999"
    bad.loc[problem == 1, "matter_id"] = "M99999"
    bad.loc[problem == 2, "hours"] = 75.0  # 7.5 typed without the point
    bad.loc[problem == 3, "posted_at"] = bad.work_date - pd.Timedelta(days=9)
    return pd.concat([time, duplicates, bad]).sample(
        frac=1, random_state=int(rng.integers(1 << 31)), ignore_index=True
    )


def generate(cfg: GenConfig | None = None) -> dict[str, pd.DataFrame]:
    """Builds every source table. The same config always yields the same data."""
    cfg = cfg or GenConfig()
    rng = np.random.default_rng(cfg.seed)
    people, rates = _timekeepers(cfg, rng)
    clients, matters, walls = _matters(cfg, rng)
    time = _time(cfg, rng, people, matters)
    lines, receipts = _bill(rng, time, matters, clients, rates, people)
    return {
        "org": pd.DataFrame(ORG, columns=["unit_id", "parent_id", "unit_name"]),
        "timekeepers": people,
        "rates": rates,
        "clients": clients.drop(columns="payment_days"),
        "matters": matters,
        "walls": walls,
        "time": _add_mess(rng, time),
        "bill_lines": lines,
        "receipts": receipts,
    }
