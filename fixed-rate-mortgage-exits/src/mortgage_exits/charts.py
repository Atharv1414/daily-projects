"""Eight charts. Each cause keeps its colour throughout, and is also labelled in words."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mortgage_exits.config import LABELS, LEFT

COLOURS = {1: "#2a78d6", 2: "#eb6834", 3: "#1baf7a", 4: "#eda100"}
INK, SOFT, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
NAMES = {
    "incentive": "Saving from moving (+1 point)",
    "shock": "Payment rise (+25%)",
    "broker": "Came through a broker",
    "ltv10": "Loan to value (+10 points)",
    "older": "Over 50",
}
# The bar a reader can picture: a 25% payment rise, not a 100% one.
STEP = {"shock": 0.25}
# Two curves end almost together; move their labels apart.
NUDGE = {"Lower or same": -0.012, "Up to 20% more": 0.012}


def _axes(title: str, width: float = 8.4, height: float = 4.6):
    fig, ax = plt.subplots(figsize=(width, height), facecolor=SURFACE)
    _style(ax)
    ax.set_title(title, loc="left", color=INK, fontsize=12.5, fontweight="bold", pad=12)
    return fig, ax


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=SOFT, labelsize=9)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#b9b8b2")
    ax.xaxis.label.set_color(SOFT)
    ax.yaxis.label.set_color(SOFT)


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)
    return path


def _percent(ax, axis: str = "y") -> None:
    formatter = matplotlib.ticker.PercentFormatter(1, decimals=0)
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(formatter)


def _fix_end(ax) -> None:
    ax.axvline(6, color=SOFT, linewidth=1, linestyle=(0, (4, 3)))
    ax.annotate(
        "fix ends",
        (6, 1),
        xycoords=("data", "axes fraction"),
        xytext=(4, -10),
        textcoords="offset points",
        color=SOFT,
        fontsize=8.5,
    )


def destinations(aj: pd.DataFrame, path: Path) -> Path:
    fig, ax = _axes("Where every 100 fixes end up")
    wide = aj.pivot(index="month", columns="cause", values="cif")
    wide.loc[0] = 0.0
    wide = wide.sort_index()
    bottom = np.zeros(len(wide))
    for k in (2, 1, 3, 4):
        top = bottom + wide[k].to_numpy()
        ax.fill_between(wide.index, bottom, top, color=COLOURS[k], edgecolor=SURFACE, linewidth=2)
        middle = (bottom[-1] + top[-1]) / 2 + (0.02 if k == 4 else 0)
        ax.text(
            24.4,
            middle,
            f"{LABELS[k]} {wide[k].iloc[-1]:.0%}",
            color=INK,
            fontsize=9.5,
            va="center",
        )
        bottom = top
    ax.text(
        24.4,
        (bottom[-1] + 1) / 2 + 0.01,
        f"Still on our standard rate {1 - bottom[-1]:.0%}",
        color=INK,
        fontsize=9.5,
        va="center",
    )
    ax.set(
        xlim=(0, 24),
        ylim=(0, 1),
        xlabel="Months since the clock started",
        ylabel="Share of mortgages",
    )
    _percent(ax)
    _fix_end(ax)
    fig.subplots_adjust(right=0.7)
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)
    return path


def naive_gap(aj: pd.DataFrame, naive: dict[int, np.ndarray], path: Path) -> Path:
    fig, ax = _axes("Ignoring competing risks overstates every exit (by month 24)")
    final = aj[aj["month"] == aj["month"].max()].set_index("cause")
    y = np.arange(4)[::-1]
    for i, k in zip(y, LABELS, strict=True):
        right, wrong = final.loc[k, "cif"], naive[k][-1]
        ax.plot([right, wrong], [i, i], color="#b9b8b2", linewidth=2, zorder=1)
        ax.scatter(
            right, i, s=70, color="#2a78d6", zorder=2, label="Aalen-Johansen" if i == 3 else None
        )
        ax.scatter(
            wrong,
            i,
            s=70,
            color="#eb6834",
            marker="D",
            zorder=2,
            label="1 minus Kaplan-Meier" if i == 3 else None,
        )
        ax.text(
            wrong + 0.015,
            i,
            f"{right:.0%} reported as {wrong:.0%}",
            va="center",
            fontsize=9,
            color=INK,
        )
    ax.set_yticks(y, LABELS.values())
    ax.set(xlim=(0, 1), ylim=(-0.6, 3.6))
    ax.grid(axis="x", color=GRID)
    ax.grid(axis="y", visible=False)
    _percent(ax, "x")
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    return _save(fig, path)


def by_shock(curves: dict[str, pd.DataFrame], path: Path) -> Path:
    fig, ax = _axes("The bigger the payment rise, the more people leave us")
    shades = ["#f5b795", "#eb8f5f", "#cf5a24", "#8a3510"]
    for (name, aj), shade in zip(curves.items(), shades, strict=True):
        part = aj[aj["cause"] == LEFT]
        ax.fill_between(
            part["month"], part["low"], part["high"], color=shade, alpha=0.2, linewidth=0
        )
        ax.plot(part["month"], part["cif"], color=shade, linewidth=2, label=name)
        ax.text(
            24.3,
            part["cif"].iloc[-1] + NUDGE.get(name, 0),
            f"{name} {part['cif'].iloc[-1]:.0%}",
            fontsize=9,
            color=INK,
            va="center",
        )
    ax.set(
        xlim=(1, 24),
        ylim=(0, None),
        xlabel="Months since the clock started",
        ylabel="Remortgaged elsewhere",
    )
    _percent(ax)
    _fix_end(ax)
    ax.legend(
        frameon=False,
        loc="lower right",
        fontsize=9,
        bbox_to_anchor=(1.0, 0.02),
        title="Monthly payment",
        alignment="left",
    )
    return _save(fig, path)


def timing(panel: pd.DataFrame, path: Path) -> Path:
    fig, axes = plt.subplots(2, 2, figsize=(8.4, 5.6), facecolor=SURFACE, sharex=True)
    for ax, k in zip(axes.flat, LABELS, strict=True):
        _style(ax)
        rate = panel.assign(hit=panel["y"] == k).groupby("month")["hit"].mean()
        ax.bar(rate.index, rate.to_numpy(), width=0.75, color=COLOURS[k])
        ax.set_title(LABELS[k], loc="left", fontsize=10, color=INK)
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.PercentFormatter(1, decimals=1 if k > 2 else 0)
        )
        ax.axvline(6.5, color=SOFT, linewidth=1, linestyle=(0, (4, 3)))
    for ax in axes[1]:
        ax.set_xlabel("Month on the clock (fix ends after month 6)")
    fig.suptitle(
        "Chance of each exit in a month, for those still here",
        x=0.02,
        ha="left",
        color=INK,
        fontsize=12.5,
        fontweight="bold",
    )
    return _save(fig, path)


def forest(ratios: pd.DataFrame, path: Path) -> Path:
    fig, ax = _axes("Hazard ratios for each exit, with 95% intervals", height=5.4)
    features = list(NAMES)
    for j, feature in enumerate(features):
        for i, k in enumerate((1, 2, 4)):
            row = ratios[(ratios["cause"] == k) & (ratios["feature"] == feature)].iloc[0]
            step = STEP.get(feature, 1.0)
            y = -j + 0.24 - 0.24 * i
            low, mid, high = (
                np.exp(step * (row["log_hr"] + z * row["se"])) for z in (-1.96, 0, 1.96)
            )
            ax.plot([low, high], [y, y], color=COLOURS[k], linewidth=2)
            ax.scatter(
                mid,
                y,
                s=44,
                color=COLOURS[k],
                marker="osD"[i],
                zorder=3,
                label=LABELS[k] if j == 0 else None,
            )
            ax.text(high * 1.02, y, f"{mid:.2f}", va="center", fontsize=8, color=SOFT)
    ax.axvline(1, color=SOFT, linewidth=1)
    ax.set_xscale("log")
    ax.set_xticks([0.6, 0.8, 1, 1.25, 1.5, 2], ["0.6", "0.8", "1", "1.25", "1.5", "2"])
    ax.minorticks_off()
    ax.set_yticks(-np.arange(len(features)), [NAMES[f] for f in features])
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3, fontsize=9)
    return _save(fig, path)


def calibration(table: pd.DataFrame, path: Path) -> Path:
    fig, ax = _axes("Forecast against what happened, on later mortgages", width=6.6, height=5.4)
    ax.plot([0, 0.8], [0, 0.8], color="#b9b8b2", linewidth=1.2, linestyle=(0, (4, 3)))
    style = {
        "Competing-risks model": ("#2a78d6", "o"),
        "Finished cases only (logistic)": ("#eb6834", "D"),
    }
    for name, (colour, marker) in style.items():
        part = table[table["model"] == name]
        ax.plot(
            part["predicted"],
            part["observed"],
            color=colour,
            marker=marker,
            linewidth=2,
            markersize=7,
            label=name,
        )
    ax.set(
        xlim=(0, 0.8),
        ylim=(0, 0.8),
        xlabel="Forecast chance of leaving within 12 months",
        ylabel="Share who left",
    )
    _percent(ax)
    _percent(ax, "x")
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    return _save(fig, path)


def gains(table: pd.DataFrame, path: Path) -> Path:
    fig, ax = _axes("Margin reached by calling the top of each list", width=7.4)
    palette = {"Chance x balance": "#2a78d6", "Balance only": "#eb6834", "Chance only": "#1baf7a"}
    for name, colour in palette.items():
        part = table[table["ranking"] == name]
        point = part[np.isclose(part["share"], 0.2)].iloc[0]
        label = f"{name}: {point['reached']:.0%} from a fifth of calls"
        ax.plot(part["share"], part["reached"], color=colour, linewidth=2, label=label)
        ax.scatter(0.2, point["reached"], s=44, color=colour, zorder=3)
    ax.plot(
        [0, 1], [0, 1], color="#b9b8b2", linewidth=1.2, linestyle=(0, (4, 3)), label="Random order"
    )
    ax.set(
        xlim=(0, 1),
        ylim=(0, 1),
        xlabel="Share of customers called",
        ylabel="Share of lost margin reached",
    )
    _percent(ax)
    _percent(ax, "x")
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    return _save(fig, path)


def break_even(table: pd.DataFrame, assumed: float, path: Path) -> Path:
    fig, ax = _axes("How often must a call work to pay for itself?", width=7.4)
    ax.bar(table["tenth"], table["break_even_save_rate"], width=0.72, color="#2a78d6")
    for x, v in zip(table["tenth"], table["break_even_save_rate"], strict=True):
        ax.text(x, v + 0.001, f"{v:.1%}", ha="center", fontsize=9, color=INK)
    ax.axhline(assumed, color=SOFT, linewidth=1.2, linestyle=(0, (4, 3)))
    ax.text(0.5, assumed + 0.001, f"planning assumption {assumed:.0%}", fontsize=9, color=SOFT)
    ax.set_xticks(table["tenth"])
    ax.set(xlabel="Tenth of customers, highest forecast loss first", ylabel="Break-even save rate")
    _percent(ax)
    return _save(fig, path)
