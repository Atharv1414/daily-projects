"""Static PNG charts for the README and docs, built from the semantic layer (executive view)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

from grocery_retail_bi.security import USERS  # noqa: E402
from grocery_retail_bi.semantic import lfl_growth, query  # noqa: E402

BLUE, AMBER, GREEN, RED, GREY = "#1f5fa8", "#d9822b", "#2e8540", "#c23934", "#9aa5b1"
GBP = FuncFormatter(lambda v, _: f"£{v / 1000:,.0f}k")
L12M = (date(2025, 11, 1), date(2026, 10, 31))


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def build_charts(conn: duckdb.DuckDBPyConnection, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ceo = USERS["ceo"]
    paths = []

    m = query(conn, ["net_sales", "target_net_sales"], ceo, by=["year_month"])
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(m.year_month, m.net_sales, color=BLUE, label="Net sales")
    ax.plot(m.year_month, m.target_net_sales, color=AMBER, ls="--", marker="o", label="Target")
    ax.yaxis.set_major_formatter(GBP)
    ax.tick_params(axis="x", rotation=60)
    ax.set_title("Monthly net sales vs target (sampled EPOS extract)")
    ax.legend()
    paths.append(_save(fig, out_dir / "01_monthly_sales_vs_target.png"))

    r = query(
        conn, ["vs_target_pct", "net_sales"], ceo, by=["region"], date_from=L12M[0], date_to=L12M[1]
    ).sort_values("vs_target_pct")
    fig, ax = plt.subplots(figsize=(8, 4))
    colours = [GREEN if v >= 0 else AMBER if v >= -0.03 else RED for v in r.vs_target_pct]
    ax.barh(r.region, r.vs_target_pct, color=colours)
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=1))
    ax.axvline(0, color="#333", lw=0.8)
    ax.set_title("Last 12 months: net sales vs target by region")
    paths.append(_save(fig, out_dir / "02_region_vs_target.png"))

    c = query(
        conn,
        ["net_sales", "gross_margin_pct", "promo_sales_share"],
        ceo,
        by=["category"],
        date_from=L12M[0],
        date_to=L12M[1],
    )
    c = c[c.category != "Unknown"]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(
        c.promo_sales_share,
        c.gross_margin_pct,
        s=c.net_sales / c.net_sales.max() * 900,
        color=BLUE,
        alpha=0.6,
    )
    for row in c.itertuples():
        ax.annotate(
            row.category,
            (row.promo_sales_share, row.gross_margin_pct),
            fontsize=8,
            ha="center",
            va="bottom",
        )
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.set_xlabel("Promo sales share")
    ax.set_ylabel("Gross margin %")
    ax.set_title("Category margin vs promotion reliance (bubble = net sales)")
    paths.append(_save(fig, out_dir / "03_category_margin_vs_promo.png"))

    lfl = lfl_growth(conn, ceo, date(2026, 1, 1), date(2026, 10, 31), by=["region"])
    lfl = lfl.dropna(subset=["lfl_growth"]).sort_values("lfl_growth")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(lfl.region, lfl.lfl_growth, color=[GREEN if v >= 0 else RED for v in lfl.lfl_growth])
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=1))
    ax.set_title("Like-for-like growth, Jan-Oct 2026 vs 2025, by current region")
    paths.append(_save(fig, out_dir / "04_lfl_growth_by_region.png"))

    d = query(conn, ["transactions", "atv"], ceo, by=["day_name"])
    order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    d = d.set_index("day_name").reindex(order)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(d.index, d.transactions, color=BLUE)
    ax2 = ax.twinx()
    ax2.plot(d.index, d.atv, color=AMBER, marker="o")
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"£{v:.2f}"))
    ax.set_ylabel("Transactions")
    ax2.set_ylabel("ATV")
    ax.set_title("Transactions (bars) and average transaction value (line) by weekday")
    paths.append(_save(fig, out_dir / "05_weekday_profile.png"))

    s = (
        query(
            conn,
            ["net_sales", "vs_target_pct"],
            ceo,
            by=["store_name"],
            date_from=L12M[0],
            date_to=L12M[1],
        )
        .dropna()
        .sort_values("vs_target_pct")
    )
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(s.vs_target_pct, bins=15, color=BLUE, edgecolor="white")
    ax.axvline(0, color="#333", lw=0.8)
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.set_title(f"Distribution of store performance vs target (n={len(s)} stores, L12M)")
    paths.append(_save(fig, out_dir / "06_store_vs_target_distribution.png"))
    return paths
