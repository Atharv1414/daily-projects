"""Static PNG charts for the README and slide decks (matplotlib, headless Agg backend)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import duckdb  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

from .dashboard import SERIES, latest_period  # noqa: E402
from .metrics import KPIS, compute_kpis  # noqa: E402
from .warehouse import query_df  # noqa: E402

TEXT, MUTED, GRID = "#191919", "#666666", "#eceef1"


def _style(ax: plt.Axes, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=TEXT, pad=12)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#c8ccd2")
    ax.spines["bottom"].set_color("#c8ccd2")
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def weekly_trend_chart(con: duckdb.DuckDBPyConnection, path: Path, depot: str = "BHM") -> Path:
    df = query_df(
        con, "SELECT * FROM v_weekly_trend WHERE depot_code IN ('ALL', ?) ORDER BY week_start", [depot]
    )
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    for i, (code, label) in enumerate([("ALL", "Network"), (depot, depot)]):
        d = df[df["depot_code"] == code]
        ax.plot(d["week_start"], d["on_time_rate"], color=SERIES[i], lw=2, marker="o", ms=4, label=label)
        ax.annotate(
            label,
            (d["week_start"].iloc[-1], d["on_time_rate"].iloc[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=TEXT,
        )
    target = KPIS["on_time_rate"].target
    ax.axhline(target, color="#9c9c9c", lw=1, ls="--")
    ax.text(df["week_start"].iloc[0], target + 0.004, f"Target {target:.0%}", color=MUTED, fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.legend(frameon=False, loc="lower left", fontsize=9)
    _style(ax, f"Weekly on-time delivery: network vs {depot}")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def depot_scorecard_chart(con: duckdb.DuckDBPyConnection, path: Path) -> Path:
    period = latest_period(con)
    depots = [r[0] for r in con.execute("SELECT depot_code FROM dim_depot ORDER BY depot_code").fetchall()]
    prev = [compute_kpis(con, d, period.prev_start, period.prev_end)["on_time_rate"] for d in depots]
    now = [compute_kpis(con, d, period.start, period.end)["on_time_rate"] for d in depots]
    order = sorted(range(len(depots)), key=lambda i: now[i])
    y = range(len(depots))
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    h = 0.38
    ax.barh(
        [i + h / 2 for i in y],
        [prev[i] for i in order],
        height=h - 0.03,
        color=SERIES[0],
        label=period.prev_label,
    )
    ax.barh(
        [i - h / 2 for i in y], [now[i] for i in order], height=h - 0.03, color=SERIES[1], label=period.label
    )
    for i, idx in enumerate(order):
        ax.text(now[idx] + 0.004, i - h / 2, f"{now[idx]:.1%}", va="center", fontsize=8, color=TEXT)
    ax.set_yticks(list(y), [depots[i] for i in order])
    ax.axvline(KPIS["on_time_rate"].target, color="#9c9c9c", lw=1, ls="--")
    ax.set_xlim(0.6, 0.92)
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    _style(ax, "On-time delivery by depot (dashed line = target)")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def utilisation_chart(con: duckdb.DuckDBPyConnection, path: Path) -> Path:
    df = query_df(con, "SELECT * FROM v_utilisation_bands ORDER BY utilisation_band")
    labels = df["utilisation_band"].str.slice(3)
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    bars = ax.bar(labels, df["on_time_rate"], color=SERIES[0], width=0.6)
    for bar, v, days in zip(bars, df["on_time_rate"], df["route_days"], strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.01, f"{v:.1%}", ha="center", fontsize=9, color=TEXT)
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            0.03,
            f"{days:,} route days",
            ha="center",
            fontsize=8,
            color="#fff",
        )
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Van utilisation on the day", color=MUTED, fontsize=9)
    _style(ax, "On-time delivery falls sharply once vans are over 95% full")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def failure_pareto_chart(con: duckdb.DuckDBPyConnection, path: Path) -> Path:
    df = query_df(con, "SELECT * FROM v_failure_pareto WHERE depot_code = 'ALL' ORDER BY reason_rank DESC")
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    ax.barh(df["failure_reason"], df["failures"], color=SERIES[0], height=0.6)
    for i, (v, s) in enumerate(zip(df["failures"], df["share"], strict=True)):
        ax.text(v + df["failures"].max() * 0.01, i, f"{v:,} ({s:.0%})", va="center", fontsize=9, color=TEXT)
    ax.set_xlim(0, df["failures"].max() * 1.18)
    _style(ax, "Why first delivery attempts fail (network, whole period)")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def build_charts(con: duckdb.DuckDBPyConnection, out_dir: str | Path) -> list[Path]:
    """Write every PNG chart into out_dir and return the paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return [
        weekly_trend_chart(con, out / "weekly_on_time_trend.png"),
        depot_scorecard_chart(con, out / "depot_on_time_scorecard.png"),
        utilisation_chart(con, out / "utilisation_vs_on_time.png"),
        failure_pareto_chart(con, out / "failure_reasons_pareto.png"),
    ]
