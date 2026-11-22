"""Seeded source-system extracts for "Harvest & Co", a fictional UK grocery chain.

Produces what a BI team typically receives:

* ``stores_snapshot.csv``: monthly snapshots of the store master. Refits change ``format``,
  a 2026 region realignment moves stores between regions, managers change, stores open and close.
* ``products_snapshot.csv``: monthly snapshots of the product master, with price rises (food
  inflation) and a category reorganisation.
* ``promotions.json``: promotion calendar from the trading team.
* ``sales_lines.csv``: a sampled EPOS transaction-line extract (~300k lines) with realistic
  mess: duplicate lines from re-sent files, returns, unknown product codes, missing loyalty
  ids, padded or lower-case store codes, and late-arriving lines.
* ``store_targets.csv``: monthly sales targets by store from finance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

START = date(2025, 1, 1)
END = date(2026, 10, 31)

REGIONS_2025 = [
    "Scotland",
    "North East",
    "North West",
    "Yorkshire",
    "Midlands",
    "Wales",
    "South West",
    "South East",
    "London",
]
TOWNS = {
    "Scotland": ["Glasgow", "Edinburgh", "Aberdeen", "Dundee"],
    "North East": ["Newcastle", "Sunderland", "Durham"],
    "North West": ["Manchester", "Liverpool", "Preston", "Chester", "Lancaster"],
    "Yorkshire": ["Leeds", "Sheffield", "York", "Hull", "Harrogate"],
    "Midlands": ["Birmingham", "Nottingham", "Leicester", "Derby", "Coventry"],
    "Wales": ["Cardiff", "Swansea", "Newport"],
    "South West": ["Bristol", "Exeter", "Bath", "Plymouth"],
    "South East": ["Brighton", "Reading", "Oxford", "Guildford", "Canterbury"],
    "London": ["Camden", "Clapham", "Greenwich", "Ealing", "Stratford", "Islington"],
}
# From 2026-04 the business merged North East into a new "North" region with Yorkshire.
REALIGNMENT_DATE = date(2026, 4, 1)
REALIGNED = {"North East": "North", "Yorkshire": "North"}

CATEGORIES = {
    "Fresh Produce": (["Fruit", "Vegetables", "Salad"], 0.34, 0.9, 3.0),
    "Bakery": (["Bread", "Cakes", "Morning Goods"], 0.38, 0.8, 3.5),
    "Dairy": (["Milk", "Cheese", "Yoghurt", "Butter"], 0.26, 0.9, 4.5),
    "Meat & Fish": (["Beef", "Chicken", "Pork", "Fish"], 0.24, 2.5, 9.0),
    "Frozen": (["Ready Meals", "Ice Cream", "Frozen Veg"], 0.30, 1.5, 5.0),
    "Ambient Grocery": (["Pasta & Rice", "Tins", "Cereal", "Sauces"], 0.29, 0.7, 4.0),
    "Drinks": (["Soft Drinks", "Juice", "Water", "Tea & Coffee"], 0.31, 0.6, 6.0),
    "Alcohol": (["Wine", "Beer", "Spirits"], 0.22, 4.0, 22.0),
    "Household": (["Cleaning", "Laundry", "Paper"], 0.33, 1.0, 9.0),
    "Health & Beauty": (["Toiletries", "Medicines", "Baby"], 0.40, 1.2, 8.0),
}
FORMATS = {"Superstore": 2.6, "Metro": 1.4, "Local": 0.8}


@dataclass(frozen=True)
class GenConfig:
    seed: int = 7
    n_stores: int = 40
    n_products: int = 420
    n_baskets: int = 120_000
    out_dir: Path = Path("data/raw")


def month_starts(start: date = START, end: date = END) -> list[date]:
    out, d = [], start.replace(day=1)
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def _stores(rng: np.random.Generator, n: int) -> pd.DataFrame:
    rows = []
    used: set[str] = set()
    regions = rng.choice(
        REGIONS_2025, size=n, p=[0.09, 0.07, 0.13, 0.11, 0.15, 0.06, 0.10, 0.13, 0.16]
    )
    for i, region in enumerate(regions):
        town = rng.choice(TOWNS[region])
        name = f"{town} {['High Street', 'Retail Park', 'Central', 'North', 'South'][i % 5]}"
        while name in used:
            name += " II"
        used.add(name)
        fmt = rng.choice(list(FORMATS), p=[0.35, 0.3, 0.35])
        opened = date(2026, int(rng.integers(2, 6)), 1) if i in (37, 38) else date(2015, 1, 1)
        closed = date(2025, 9, 30) if i == 39 else None
        rows.append(
            dict(
                store_code=f"S{100 + i:03d}",
                store_name=name,
                town=town,
                region=region,
                format=fmt,
                manager=f"Manager {i:02d}A",
                opened_on=opened,
                closed_on=closed,
                size_sqft=int(FORMATS[fmt] * 9_000 * rng.uniform(0.8, 1.2)),
            )
        )
    return pd.DataFrame(rows)


def _store_snapshots(rng: np.random.Generator, stores: pd.DataFrame) -> pd.DataFrame:
    refits = {
        code: month_starts()[int(rng.integers(4, 18))]
        for code in rng.choice(stores.store_code, size=6, replace=False)
    }
    manager_moves = {
        code: month_starts()[int(rng.integers(2, 20))]
        for code in rng.choice(stores.store_code, size=8, replace=False)
    }
    snaps = []
    for m in month_starts():
        for s in stores.itertuples():
            if s.opened_on > m or (s.closed_on and s.closed_on < m):
                continue
            fmt = s.format
            if s.store_code in refits and m >= refits[s.store_code] and fmt == "Local":
                fmt = "Metro"
            region = REALIGNED.get(s.region, s.region) if m >= REALIGNMENT_DATE else s.region
            manager = s.manager
            if s.store_code in manager_moves and m >= manager_moves[s.store_code]:
                manager = s.manager.replace("A", "B")
            snaps.append(
                dict(
                    snapshot_date=m,
                    store_code=s.store_code,
                    store_name=s.store_name,
                    town=s.town,
                    region=region,
                    format=fmt,
                    manager=manager,
                    size_sqft=s.size_sqft,
                    opened_on=s.opened_on,
                    closed_on=s.closed_on,
                )
            )
    return pd.DataFrame(snaps)


def _products(rng: np.random.Generator, n: int) -> pd.DataFrame:
    rows = []
    cats = list(CATEGORIES)
    weights = np.array([0.14, 0.08, 0.12, 0.1, 0.08, 0.16, 0.1, 0.08, 0.08, 0.06])
    for i in range(n):
        cat = cats[int(rng.choice(len(cats), p=weights / weights.sum()))]
        subs, margin, lo, hi = CATEGORIES[cat]
        price = round(float(rng.uniform(lo, hi)), 2)
        own_label = bool(rng.random() < 0.45)
        m = margin + (0.08 if own_label else 0) + rng.normal(0, 0.03)
        rows.append(
            dict(
                product_code=f"P{10000 + i}",
                product_name=f"{rng.choice(subs)} item {i}",
                category=cat,
                subcategory=str(rng.choice(subs)),
                brand="Harvest & Co" if own_label else f"Brand {int(rng.integers(1, 60))}",
                own_label=own_label,
                base_price=price,
                unit_cost=round(price * (1 - max(0.05, m)), 2),
            )
        )
    return pd.DataFrame(rows)


def _product_snapshots(rng: np.random.Generator, products: pd.DataFrame) -> pd.DataFrame:
    months = month_starts()
    rise_month = {
        c: months[int(rng.integers(1, len(months)))]
        for c in rng.choice(products.product_code, size=int(len(products) * 0.35), replace=False)
    }
    reorg = set(products[products.subcategory == "Ready Meals"].product_code)
    snaps = []
    for m in months:
        df = products.copy()
        df["snapshot_date"] = m
        risen = df.product_code.map(lambda c, m=m: c in rise_month and m >= rise_month[c])
        df.loc[risen, "base_price"] = (df.loc[risen, "base_price"] * 1.08).round(2)
        df.loc[risen, "unit_cost"] = (df.loc[risen, "unit_cost"] * 1.09).round(2)
        # Category reorganisation: Ready Meals move from Frozen to a new "Food To Go" category.
        if m >= date(2026, 1, 1):
            df.loc[df.product_code.isin(reorg), "category"] = "Food To Go"
        snaps.append(df)
    return pd.concat(snaps, ignore_index=True)


def _promotions(rng: np.random.Generator, products: pd.DataFrame) -> list[dict]:
    promos = []
    names = [
        "Summer BBQ",
        "Back to School",
        "Christmas Big Shop",
        "New Year Healthy",
        "Easter Treats",
        "Big Night In",
        "Brew Better",
        "Spring Clean",
        "Half Term Snacks",
        "Bonfire Night",
        "Burns Night",
        "Six Nations Beers",
    ]
    cats = list(CATEGORIES)
    for i in range(26):
        start = START + timedelta(days=int(rng.integers(0, (END - START).days - 21)))
        cat = rng.choice(cats)
        codes = (
            products[products.category == cat]
            .product_code.sample(
                n=min(25, int((products.category == cat).sum())),
                random_state=int(rng.integers(1e6)),
            )
            .tolist()
        )
        promos.append(
            dict(
                promo_code=f"PR{i + 1:03d}",
                promo_name=f"{names[i % len(names)]} {start.year}",
                mechanic=str(rng.choice(["% off", "Multibuy", "Loyalty price"])),
                discount_pct=float(rng.choice([0.1, 0.15, 0.2, 0.25, 0.33])),
                start_date=start.isoformat(),
                end_date=(start + timedelta(days=int(rng.integers(7, 22)))).isoformat(),
                product_codes=codes,
            )
        )
    return promos


def _sales(
    rng: np.random.Generator,
    cfg: GenConfig,
    stores: pd.DataFrame,
    store_snaps: pd.DataFrame,
    product_snaps: pd.DataFrame,
    promos: list[dict],
) -> pd.DataFrame:
    days = pd.date_range(START, END, freq="D")
    dow = np.array([1.0, 0.9, 0.95, 1.0, 1.15, 1.35, 1.1])
    season = np.where(days.month == 12, 1.45, 1.0) * np.where(days.month.isin([7, 8]), 1.08, 1.0)
    growth = np.linspace(1.0, 1.12, len(days))
    day_w = dow[days.day_of_week] * season * growth
    open_mask = np.array(
        [
            [
                (s.opened_on <= d.date()) and (s.closed_on is None or d.date() <= s.closed_on)
                for d in days
            ]
            for s in stores.itertuples()
        ]
    )
    store_w = stores.format.map(FORMATS).to_numpy()[:, None] * open_mask * day_w[None, :]
    p = (store_w / store_w.sum()).ravel()
    picks = rng.choice(p.size, size=cfg.n_baskets, p=p)
    store_idx, day_idx = np.divmod(picks, len(days))

    # Price lookup per (month, product) from the snapshots.
    snap = product_snaps.copy()
    snap["ym"] = pd.to_datetime(snap.snapshot_date).dt.to_period("M")
    price = snap.set_index(["ym", "product_code"])[["base_price"]]
    codes = product_snaps.product_code.unique()
    pop = rng.zipf(1.6, size=len(codes)).astype(float)
    pop = np.minimum(pop, 50)
    pop /= pop.sum()

    promo_index: dict[str, list[tuple[pd.Timestamp, pd.Timestamp, str, float]]] = {}
    for pr in promos:
        for code in pr["product_codes"]:
            promo_index.setdefault(code, []).append(
                (
                    pd.Timestamp(pr["start_date"]),
                    pd.Timestamp(pr["end_date"]),
                    pr["promo_code"],
                    pr["discount_pct"],
                )
            )

    n_lines = rng.poisson(2.5, size=cfg.n_baskets) + 1
    rows_basket = np.repeat(np.arange(cfg.n_baskets), n_lines)
    line_prod = rng.choice(codes, size=rows_basket.size, p=pop)
    line_day = days[day_idx[rows_basket]]
    qty = rng.choice([1, 1, 1, 2, 2, 3, 4], size=rows_basket.size)
    ym = line_day.to_period("M")
    unit_price = price.reindex(pd.MultiIndex.from_arrays([ym, line_prod])).base_price.to_numpy()
    promo_code = np.full(rows_basket.size, None, dtype=object)
    discount = np.zeros(rows_basket.size)
    for i in np.flatnonzero(np.isin(line_prod, list(promo_index))):
        for start, end, code, pct in promo_index[line_prod[i]]:
            if start <= line_day[i] <= end:
                promo_code[i], discount[i] = code, pct
                qty[i] += int(rng.random() < 0.4)  # promo uplift
                break
    gross = np.round(unit_price * qty, 2)
    disc_amt = np.round(gross * discount, 2)
    basket_minute = rng.integers(7 * 60, 22 * 60, cfg.n_baskets)
    loyalty = pd.array(rng.integers(100_000, 160_000, size=cfg.n_baskets), dtype="Int64")
    loyalty[rng.random(cfg.n_baskets) < 0.38] = pd.NA
    df = pd.DataFrame(
        {
            "line_id": [f"L{i:07d}" for i in range(rows_basket.size)],
            "basket_id": [f"B{b:07d}" for b in rows_basket],
            "store_code": stores.store_code.to_numpy()[store_idx[rows_basket]],
            "sale_ts": line_day + pd.to_timedelta(basket_minute[rows_basket], unit="m"),
            "product_code": line_prod,
            "quantity": qty,
            "unit_price": unit_price,
            "discount_amount": disc_amt,
            "net_amount": np.round(gross - disc_amt, 2),
            "promo_code": promo_code,
            "loyalty_id": loyalty[rows_basket],
        }
    )
    # Returns: ~1% of lines are refunded a few days later as negative lines.
    ret = df.sample(frac=0.01, random_state=cfg.seed).copy()
    ret["line_id"] = ret.line_id.str.replace("L", "R", regex=False)
    ret["basket_id"] = ret.basket_id.str.replace("B", "RB", regex=False)
    ret["sale_ts"] = ret.sale_ts + pd.to_timedelta(rng.integers(1, 6, len(ret)), unit="D")
    ret = ret[ret.sale_ts <= pd.Timestamp(END) + pd.Timedelta(hours=23)]
    for col in ("quantity", "discount_amount", "net_amount"):
        ret[col] = -ret[col]
    df = pd.concat([df, ret], ignore_index=True)
    df["loaded_at"] = df.sale_ts.dt.normalize() + pd.Timedelta(days=1, hours=2)
    late = rng.random(len(df)) < 0.02  # late-arriving tills
    df.loc[late, "loaded_at"] += pd.to_timedelta(rng.integers(3, 20, int(late.sum())), unit="D")
    unknown = rng.random(len(df)) < 0.003
    df.loc[unknown, "product_code"] = "P99999"
    messy = rng.random(len(df)) < 0.02
    df.loc[messy, "store_code"] = " " + df.loc[messy, "store_code"].str.lower() + " "
    dupes = df.sample(frac=0.005, random_state=cfg.seed + 1)  # re-sent till files
    df = pd.concat([df, dupes], ignore_index=True)
    return df.sort_values(["loaded_at", "line_id"], kind="stable").reset_index(drop=True)


def _targets(rng: np.random.Generator, sales: pd.DataFrame, stores: pd.DataFrame) -> pd.DataFrame:
    s = sales.drop_duplicates("line_id").copy()
    s["store_code"] = s.store_code.str.strip().str.upper()
    s["month"] = s.sale_ts.dt.to_period("M").dt.to_timestamp()
    actual = s.groupby(["store_code", "month"]).net_amount.sum()
    out = []
    for (code, month), value in actual.items():
        out.append(
            dict(
                store_code=code,
                month=month.date(),
                target_net_sales=round(float(value) * rng.normal(1.02, 0.06), 2),
            )
        )
    return pd.DataFrame(out)


def generate(cfg: GenConfig = GenConfig()) -> dict[str, Path]:
    rng = np.random.default_rng(cfg.seed)
    stores = _stores(rng, cfg.n_stores)
    store_snaps = _store_snapshots(rng, stores)
    products = _products(rng, cfg.n_products)
    product_snaps = _product_snapshots(rng, products)
    promos = _promotions(rng, products)
    sales = _sales(rng, cfg, stores, store_snaps, product_snaps, promos)
    targets = _targets(rng, sales, stores)
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "stores": cfg.out_dir / "stores_snapshot.csv",
        "products": cfg.out_dir / "products_snapshot.csv",
        "promotions": cfg.out_dir / "promotions.json",
        "sales": cfg.out_dir / "sales_lines.csv",
        "targets": cfg.out_dir / "store_targets.csv",
    }
    store_snaps.to_csv(paths["stores"], index=False)
    product_snaps.to_csv(paths["products"], index=False)
    paths["promotions"].write_text(json.dumps(promos, indent=1), encoding="utf-8")
    sales.to_csv(paths["sales"], index=False)
    targets.to_csv(paths["targets"], index=False)
    return paths
