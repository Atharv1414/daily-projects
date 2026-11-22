"""Charts for the business case (matplotlib, PNG)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from fnol_business_case.analysis import Comparison  # noqa: E402
from fnol_business_case.datagen import PILOT_START  # noqa: E402
from fnol_business_case.finance import MonteCarlo  # noqa: E402
from fnol_business_case.risks import Risk  # noqa: E402
from fnol_business_case.stakeholders import Stakeholder  # noqa: E402

BLUE, AMBER, GREEN, RED, GREY = "#1f5fa8", "#d9822b", "#2e8540", "#c23934", "#9aa5b1"
GBP_M = FuncFormatter(lambda v, _: f"£{v / 1e6:.1f}m")


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def channel_mix(df: pd.DataFrame, out: Path) -> Path:
    g = df.groupby(["month", "channel"]).size().unstack(fill_value=0)
    g = g[[c for c in ["Phone", "Digital", "Broker", "Email"] if c in g]]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.stackplot(
        range(len(g)),
        g.T.to_numpy(),
        labels=g.columns,
        colors=[GREY, BLUE, AMBER, GREEN][: len(g.columns)],
        alpha=0.9,
    )
    ax.set_xticks(range(0, len(g), 2), g.index[::2], rotation=45)
    ax.set_ylabel("Claims notified")
    ax.set_title("Claims by FNOL channel (digital pilot in 2 regions from May 2026)")
    ax.legend(loc="upper left")
    return _save(fig, out / "01_channel_mix.png")


def did_trend(df: pd.DataFrame, out: Path) -> Path:
    s = df[df.status == "Settled"]
    g = s.groupby(["month", "in_pilot_region"]).days_to_settle.mean().unstack()
    g = g[g.index <= "2026-08"]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(g.index, g[True], marker="o", color=BLUE, label="Pilot regions (NW, Scotland)")
    ax.plot(g.index, g[False], marker="o", color=GREY, label="Control regions")
    launch = list(g.index).index(PILOT_START.strftime("%Y-%m"))
    ax.axvline(launch - 0.5, color=AMBER, ls="--", label="Pilot launch")
    ax.tick_params(axis="x", rotation=45)
    ax.set_ylabel("Mean days to settle")
    ax.set_title("Difference-in-differences: settlement time, pilot vs control")
    ax.legend()
    return _save(fig, out / "02_did_cycle_time.png")


def comparison(comps: list[Comparison], out: Path) -> Path:
    fig, axes = plt.subplots(1, len(comps), figsize=(12, 3.6))
    for ax, c in zip(axes, comps, strict=True):
        ax.bar(["Phone", "Digital"], [c.phone_mean, c.digital_mean], color=[GREY, BLUE])
        ax.set_title(
            f"{c.metric}\nΔ {c.difference:+.1f} (95% CI {c.ci_low:+.1f} to {c.ci_high:+.1f})",
            fontsize=9,
        )
    fig.suptitle("Simple claims in pilot regions after launch: digital vs phone", fontsize=11)
    return _save(fig, out / "03_digital_vs_phone.png")


def hire_vs_cycle(df: pd.DataFrame, slope: float, out: Path) -> Path:
    r = df[(df.rental_days > 0) & df.days_to_settle.notna()].sample(3_000, random_state=1)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.scatter(r.days_to_settle, r.rental_days, s=6, alpha=0.3, color=BLUE)
    x = np.linspace(0, r.days_to_settle.max(), 50)
    intercept = (r.rental_days - slope * r.days_to_settle).mean()
    ax.plot(x, intercept + slope * x, color=RED, label=f"{slope:.2f} hire days per cycle day")
    ax.set_xlabel("Days to settle")
    ax.set_ylabel("Hire-car days")
    ax.set_title("Every extra day of cycle time adds hire-car cost")
    ax.legend()
    return _save(fig, out / "04_hire_vs_cycle.png")


def tornado_chart(t: pd.DataFrame, out: Path, top: int = 10) -> Path:
    t = t.head(top).iloc[::-1]
    base = t.base_npv.iloc[0]
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, row in enumerate(t.itertuples()):
        lo, hi = sorted([row.npv_low, row.npv_high])
        ax.barh(i, hi - base, left=base, color=GREEN)
        ax.barh(i, lo - base, left=base, color=RED)
    ax.set_yticks(range(len(t)), t.assumption, fontsize=8)
    ax.axvline(base, color="#333", lw=1)
    ax.axvline(0, color=RED, lw=1, ls=":")
    ax.xaxis.set_major_formatter(GBP_M)
    ax.set_title(f"NPV sensitivity (base £{base / 1e6:.2f}m): each assumption at low / high")
    return _save(fig, out / "05_tornado.png")


def monte_carlo_chart(mc: MonteCarlo, out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(mc.npvs, bins=60, color=BLUE, alpha=0.85)
    for v, label in ((mc.p10, "P10"), (mc.p50, "P50"), (mc.p90, "P90")):
        ax.axvline(v, color=AMBER, ls="--")
        ax.text(v, ax.get_ylim()[1] * 0.92, label, ha="center", fontsize=8)
    ax.axvline(0, color=RED)
    ax.xaxis.set_major_formatter(GBP_M)
    ax.set_title(f"Monte Carlo NPV, {len(mc.npvs):,} runs: P(NPV > 0) = {mc.p_positive:.0%}")
    return _save(fig, out / "06_monte_carlo.png")


def cumulative_cash(series: dict[str, np.ndarray], out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    colours = {"Pessimistic": RED, "Base": BLUE, "Optimistic": GREEN}
    for label, net in series.items():
        ax.plot(range(len(net)), np.cumsum(net), marker="o", label=label, color=colours[label])
    ax.axhline(0, color="#333", lw=0.8)
    ax.yaxis.set_major_formatter(GBP_M)
    ax.set_xticks(range(len(net)), [f"Y{i}" for i in range(len(net))])
    ax.set_title("Cumulative net cash flow by scenario (undiscounted)")
    ax.legend()
    return _save(fig, out / "07_cumulative_cash.png")


def power_interest(people: list[Stakeholder], out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 6))
    colours = {"Supportive": GREEN, "Neutral": GREY, "Concerned": RED}
    rng = np.random.default_rng(0)
    for p in people:
        x, y = p.interest + rng.uniform(-0.18, 0.18), p.power + rng.uniform(-0.18, 0.18)
        ax.scatter(x, y, s=120, color=colours.get(p.stance, BLUE))
        ax.annotate(p.name, (x, y), fontsize=7, xytext=(5, 4), textcoords="offset points")
    ax.axhline(2.5, color="#333", lw=0.6)
    ax.axvline(2.5, color="#333", lw=0.6)
    for (x, y), label in {
        (4.6, 5.4): "Manage closely",
        (1.2, 5.4): "Keep satisfied",
        (4.6, 0.7): "Keep informed",
        (1.2, 0.7): "Monitor",
    }.items():
        ax.text(x, y, label, fontsize=9, color="#555", ha="center")
    ax.set(
        xlim=(0.5, 5.8),
        ylim=(0.5, 5.6),
        xlabel="Interest",
        ylabel="Power",
        title="Stakeholder map (colour = stance)",
    )
    return _save(fig, out / "08_stakeholder_map.png")


def risk_heatmap(risks: list[Risk], out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), sharey=True)
    grid = np.add.outer(np.arange(1, 6), np.arange(1, 6))
    for ax, title, resid in ((axes[0], "Inherent", False), (axes[1], "Residual", True)):
        ax.imshow(grid, origin="lower", cmap="RdYlGn_r", extent=(0.5, 5.5, 0.5, 5.5), alpha=0.5)
        for r in risks:
            li, im = (
                (r.residual_likelihood, r.residual_impact) if resid else (r.likelihood, r.impact)
            )
            ax.text(
                im,
                li,
                r.id,
                ha="center",
                va="center",
                fontsize=8,
                bbox=dict(boxstyle="circle", fc="white", ec="#333"),
            )
        ax.set(title=f"{title} risk", xlabel="Impact", xticks=range(1, 6), yticks=range(1, 6))
    axes[0].set_ylabel("Likelihood")
    return _save(fig, out / "09_risk_heatmap.png")
