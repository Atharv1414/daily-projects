"""Seeded generator of realistic, deliberately messy UK bank statements.

The output imitates real exports: mixed date formats, card references and payment prefixes
in descriptions, currency symbols and thousands separators, income and refunds mixed in,
a handful of corrupt rows, a few genuine one-off large purchases, and two statement files
whose date ranges overlap (as happens when you download a new statement every month).
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .models import add_months


@dataclass(frozen=True)
class MerchantProfile:
    descriptions: tuple[str, ...]
    per_week: float
    median_pounds: float
    spread: float = 0.35


PROFILES: tuple[MerchantProfile, ...] = (
    MerchantProfile(("TESCO STORES {n}", "TESCO EXPRESS {n}"), 2.5, 24.0),
    MerchantProfile(("SAINSBURYS S/MKTS",), 1.0, 38.0),
    MerchantProfile(("PRET A MANGER", "GREGGS PLC", "COSTA COFFEE {n}"), 3.0, 5.2, 0.4),
    MerchantProfile(("DELIVEROO",), 0.6, 27.0),
    MerchantProfile(("TFL TRAVEL CH", "TFL.GOV.UK/CP"), 4.0, 6.8, 0.3),
    MerchantProfile(("UBER *TRIP",), 0.4, 14.0, 0.5),
    MerchantProfile(("TRAINLINE.COM",), 0.2, 46.0),
    MerchantProfile(("AMZN MKTP UK*{ref}",), 0.9, 21.0, 0.7),
    MerchantProfile(("ASOS.COM", "PRIMARK {n}"), 0.25, 35.0, 0.5),
    MerchantProfile(("ODEON CINEMAS", "TICKETMASTER UK"), 0.3, 22.0, 0.5),
    MerchantProfile(("BOOTS {n}",), 0.5, 11.0, 0.5),
)

MONTHLY_BILLS: tuple[tuple[str, int, float], ...] = (
    ("DIRECT DEBIT TO FOXTONS RENT", 1, 1450.00),
    ("DIRECT DEBIT TO LAMBETH COUNCIL TAX", 3, 142.00),
    ("DIRECT DEBIT TO OCTOPUS ENERGY", 5, 96.00),
    ("DIRECT DEBIT TO THAMES WATER", 8, 38.50),
    ("DIRECT DEBIT TO VIRGIN MEDIA", 12, 52.00),
    ("NETFLIX.COM", 14, 10.99),
    ("SPOTIFY UK", 15, 11.99),
    ("PUREGYM LTD", 1, 32.99),
)

ONE_OFF_SPIKES: tuple[tuple[str, float], ...] = (
    ("CURRYS PC WORLD {n}", 899.00),
    ("JOHN LEWIS {n}", 640.00),
    ("TRAINLINE.COM", 312.40),
    ("DELIVEROO", 186.50),
    ("BOOTS {n}", 154.00),
)


def _fmt_date(d: date, rng: random.Random) -> str:
    return d.isoformat() if rng.random() < 0.7 else d.strftime("%d/%m/%Y")


def _fmt_amount(signed: float, rng: random.Random) -> str:
    text = f"{abs(signed):,.2f}" if rng.random() < 0.3 else f"{abs(signed):.2f}"
    if rng.random() < 0.1:
        text = "£" + text
    return ("-" if signed < 0 else "") + text


def _describe(template: str, rng: random.Random) -> str:
    desc = template.format(
        n=rng.randint(1000, 9999), ref=f"{rng.randint(10, 99)}X{rng.random():.3f}"[:8]
    )
    if rng.random() < 0.35:
        desc = f"CARD PAYMENT TO {desc}*{rng.randint(1000, 9999)}"
    if rng.random() < 0.05:
        desc = f"  {desc}   "
    return desc


def generate_transactions(start: date, months: int, seed: int = 42) -> list[dict[str, str]]:
    """Return statement rows (Date, Description, Amount; negative = money out), date-ordered."""
    rng = random.Random(seed)
    end = add_months(start, months) - timedelta(days=1)
    rows: list[tuple[date, str, float]] = []

    day = start
    while day <= end:
        for profile in PROFILES:
            if rng.random() < profile.per_week / 7:
                amount = round(rng.lognormvariate(0, profile.spread) * profile.median_pounds, 2)
                rows.append((day, _describe(rng.choice(profile.descriptions), rng), -amount))
        if day.day == 25:
            rows.append((day, "ACME ANALYTICS LTD SALARY", 3125.00))
        for desc, bill_day, amount in MONTHLY_BILLS:
            if day.day == bill_day:
                rows.append((day, desc, -amount))
        if rng.random() < 0.015:  # refunds come back as credits
            rows.append((day, _describe("AMZN MKTP UK*{ref}", rng), round(rng.uniform(5, 60), 2)))
        day += timedelta(days=1)

    for template, amount in ONE_OFF_SPIKES:
        when = start + timedelta(days=rng.randrange((end - start).days + 1))
        rows.append((when, _describe(template, rng), -amount))

    rows.sort(key=lambda r: r[0])
    out = [
        {"Date": _fmt_date(d, rng), "Description": desc, "Amount": _fmt_amount(a, rng)}
        for d, desc, a in rows
    ]
    # Corrupt ~0.5% of rows the way real exports occasionally are.
    for row in rng.sample(out, k=max(3, len(out) // 200)):
        fault = rng.choice(("blank_amount", "bad_amount", "bad_date", "blank_desc"))
        if fault == "blank_amount":
            row["Amount"] = ""
        elif fault == "bad_amount":
            row["Amount"] = "N/A"
        elif fault == "bad_date":
            row["Date"] = "31/02/2025"
        else:
            row["Description"] = ""
    return out


def write_amount_csv(rows: list[dict[str, str]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["Date", "Description", "Amount"])
        writer.writeheader()
        writer.writerows(rows)


def write_debit_credit_csv(rows: list[dict[str, str]], path: Path) -> None:
    """A second bank's layout: separate Paid out / Paid in columns and different headers."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Transaction Date", "Details", "Paid out", "Paid in"])
        for r in rows:
            amount = r["Amount"]
            out, inn = (amount[1:], "") if amount.startswith("-") else ("", amount)
            if amount in ("", "N/A"):
                out, inn = amount, ""
            writer.writerow([r["Date"], r["Description"], out, inn])


def write_sample_statements(
    out_dir: Path, start: date = date(2024, 12, 1), months: int = 23, seed: int = 42
) -> list[Path]:
    """Write two statements that overlap by two months, in two different bank formats."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = generate_transactions(start, months, seed)
    split_a = add_months(start, 13)  # first file: months 0-12
    split_b = add_months(start, 11)  # second file: months 11-22 (2 months overlap)

    def row_date(r: dict[str, str]) -> date | None:
        text = r["Date"]
        try:
            if "/" in text:
                d, m, y = map(int, text.split("/"))
                return date(y, m, d)
            return date.fromisoformat(text)
        except ValueError:
            return None

    first = [r for r in rows if (d := row_date(r)) is None or d < split_a]
    second = [r for r in rows if (d := row_date(r)) is not None and d >= split_b]
    a, b = out_dir / "bank_a_statement.csv", out_dir / "bank_b_statement.csv"
    write_amount_csv(first, a)
    write_debit_credit_csv(second, b)
    return [a, b]
