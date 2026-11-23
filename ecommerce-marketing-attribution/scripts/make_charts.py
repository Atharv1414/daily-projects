"""Render README charts from the built marts.

Usage (after `dbt build --profiles-dir .`):
    pip install -r scripts/requirements-charts.txt
    python scripts/make_charts.py
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "charts"
MODELS = ["last_touch", "first_touch", "position_based"]
COLOURS = {"last_touch": "#9aa0a6", "first_touch": "#2a6fdb", "position_based": "#e0533d"}


def save(fig: plt.Figure, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=110)
    plt.close(fig)
    print(OUT / name)


def roas_by_model(con: duckdb.DuckDBPyConnection) -> None:
    df = con.execute(
        "select channel, model, roas, spend_gbp from marts.mart_channel_attribution "
        "where spend_gbp > 0 order by spend_gbp desc"
    ).df()
    channels = df.drop_duplicates("channel")["channel"].tolist()
    fig, ax = plt.subplots(figsize=(9, 4.2))
    width = 0.27
    for i, model in enumerate(MODELS):
        values = [df[(df.channel == c) & (df.model == model)]["roas"].iloc[0] for c in channels]
        ax.bar([x + (i - 1) * width for x in range(len(channels))], values, width,
               label=model.replace("_", " "), color=COLOURS[model])
    ax.axhline(1, color="#333", lw=0.8, ls="--")
    ax.set_xticks(range(len(channels)), [c.replace("_", "\n") for c in channels], fontsize=8)
    ax.set_ylabel("ROAS (attributed revenue / spend)")
    ax.set_title("Paid channel ROAS depends on the attribution model")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)
    save(fig, "roas_by_model.png")


def credit_shift(con: duckdb.DuckDBPyConnection) -> None:
    df = con.execute(
        "select channel, revenue_vs_last_touch_gbp as shift from marts.mart_channel_attribution "
        "where model = 'position_based' order by shift"
    ).df()
    fig, ax = plt.subplots(figsize=(8, 4))
    colours = ["#e0533d" if v < 0 else "#2f9e6e" for v in df["shift"]]
    ax.barh(df["channel"], df["shift"] / 1000, color=colours)
    ax.axvline(0, color="#333", lw=0.8)
    ax.set_xlabel("£k revenue credit vs last-touch")
    ax.set_title("Position-based vs last-touch: who gains and who loses credit")
    ax.grid(axis="x", alpha=0.25)
    save(fig, "credit_shift_vs_last_touch.png")


def lift(con: duckdb.DuckDBPyConnection) -> None:
    df = con.execute(
        "select channel, conversion_rate_with * 100 as w, conversion_rate_without * 100 as wo "
        "from marts.mart_channel_lift order by relative_lift desc"
    ).df()
    fig, ax = plt.subplots(figsize=(9, 4))
    x = range(len(df))
    ax.bar([i - 0.2 for i in x], df["w"], 0.4, label="journeys with channel", color="#2a6fdb")
    ax.bar([i + 0.2 for i in x], df["wo"], 0.4, label="journeys without", color="#c9d6ea")
    ax.set_xticks(list(x), [c.replace("_", "\n") for c in df["channel"]], fontsize=8)
    ax.set_ylabel("visitor conversion rate (%)")
    ax.set_title("Conversion rate of journeys with vs without each channel")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)
    save(fig, "channel_lift.png")


def top_paths(con: duckdb.DuckDBPyConnection) -> None:
    df = con.execute(
        "select channel_path, conversions from marts.mart_conversion_paths "
        "order by conversions desc limit 12"
    ).df().iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.barh(df["channel_path"], df["conversions"], color="#2a6fdb")
    ax.set_xlabel("conversions")
    ax.set_title("Top converting paths (consecutive repeats collapsed)")
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(axis="x", alpha=0.25)
    save(fig, "top_paths.png")


def monthly(con: duckdb.DuckDBPyConnection) -> None:
    df = con.execute(
        "select revenue_month, revenue_gbp, spend_gbp, roas from marts.mart_monthly_rollup "
        "where grouping_level = 3 order by revenue_month"
    ).df()
    fig, ax = plt.subplots(figsize=(8, 3.8))
    labels = df["revenue_month"].dt.strftime("%b")
    ax.bar(labels, df["revenue_gbp"] / 1000, color="#2f9e6e", label="attributed revenue")
    ax.bar(labels, df["spend_gbp"] / 1000, color="#e0533d", label="media spend", width=0.45)
    for i, r in enumerate(df["roas"]):
        ax.annotate(f"ROAS {r:.2f}", (i, df["revenue_gbp"].iloc[i] / 1000), ha="center",
                    va="bottom", fontsize=8)
    ax.set_ylabel("£k")
    ax.set_ylim(0, df["revenue_gbp"].max() / 1000 * 1.18)
    ax.set_title("Monthly revenue vs spend (position-based)")
    ax.legend(frameon=False, loc="upper left", ncol=2)
    save(fig, "monthly_revenue_vs_spend.png")


def path_length(con: duckdb.DuckDBPyConnection) -> None:
    df = con.execute(
        "select least(touch_count, 8) as touches, count(*) as orders from marts.fct_orders "
        "group by 1 order by 1"
    ).df()
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.bar(df["touches"].astype(str).replace({"8": "8+"}), df["orders"], color="#2a6fdb")
    ax.set_xlabel("touches in the 30-day lookback window")
    ax.set_ylabel("orders")
    ax.set_title("How many visits does a purchase take?")
    ax.grid(axis="y", alpha=0.25)
    save(fig, "touches_per_order.png")


def main() -> None:
    con = duckdb.connect(str(ROOT / "target" / "warehouse.duckdb"), read_only=True)
    for chart in (roas_by_model, credit_shift, lift, top_paths, monthly, path_length):
        chart(con)


if __name__ == "__main__":
    main()
