"""All figures for the report. Each function saves one PNG and returns its path."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from outpatient_dna.config import TRIAL_END, TRIAL_START  # noqa: E402

BLUE, ORANGE, GREY, RED = "#2b6cb0", "#dd6b20", "#718096", "#c53030"
plt.rcParams.update(
    {
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "font.size": 9,
    }
)


def _save(fig, out: Path, name: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def _err(t: pd.DataFrame) -> np.ndarray:
    return np.vstack([t["dna_rate"] - t["ci_low"], t["ci_high"] - t["dna_rate"]]) * 100


def rate_bars(
    t: pd.DataFrame, col: str, title: str, out: Path, name: str, overall: float, sort: bool = True
) -> Path:
    t = t.sort_values("dna_rate") if sort else t
    fig, ax = plt.subplots(figsize=(7.5, 0.35 * len(t) + 1.4))
    ax.barh(
        t[col].astype(str),
        t["dna_rate"] * 100,
        xerr=_err(t),
        color=BLUE,
        alpha=0.85,
        error_kw={"elinewidth": 1, "ecolor": GREY},
    )
    ax.axvline(overall * 100, color=RED, linestyle="--", linewidth=1)
    ax.text(overall * 100, -0.9, f" trust average {overall:.1%}", color=RED, fontsize=8)
    ax.set_xlabel("DNA rate (%) with 95% CI")
    ax.set_title(title)
    return _save(fig, out, name)


def age_and_deprivation(age: pd.DataFrame, imd: pd.DataFrame, out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].bar(
        age["age_band"],
        age["dna_rate"] * 100,
        yerr=_err(age),
        color=BLUE,
        error_kw={"ecolor": GREY},
    )
    axes[0].set_title("DNA rate by age band")
    axes[0].set_ylabel("DNA rate (%)")
    known = imd[imd["imd_group"] != "Unknown"].copy()
    known["d"] = known["imd_group"].astype(int)
    known = known.sort_values("d")
    axes[1].errorbar(
        known["d"], known["dna_rate"] * 100, yerr=_err(known), marker="o", color=ORANGE, capsize=3
    )
    axes[1].set_xticks(range(1, 11))
    axes[1].set_xlabel("IMD decile (1 = most deprived)")
    axes[1].set_title("DNA rate by deprivation")
    return _save(fig, out, "02_age_and_deprivation.png")


def lead_time(t: pd.DataFrame, out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.errorbar(
        t["lead_band"].astype(str),
        t["dna_rate"] * 100,
        yerr=_err(t),
        marker="o",
        color=BLUE,
        capsize=3,
    )
    ax.set_ylabel("DNA rate (%)")
    ax.set_xlabel("days between booking and appointment")
    ax.set_title("Longer waits between booking and appointment mean more DNAs")
    return _save(fig, out, "03_lead_time.png")


def weekly_trend(series: pd.DataFrame, out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.plot(series.index, series["dna_rate"] * 100, color=BLUE, linewidth=1.2)
    ax.plot(
        series.index,
        (series["dna_rate"] * 100).rolling(8, center=True).mean(),
        color=RED,
        linewidth=2,
        label="8-week rolling mean",
    )
    ax.axvspan(
        pd.Timestamp(TRIAL_START),
        pd.Timestamp(TRIAL_END),
        color=ORANGE,
        alpha=0.12,
        label="SMS trial (half of patients got the new message)",
    )
    ax.set_ylabel("weekly DNA rate (%)")
    ax.set_title("Weekly DNA rate, 2024–2025")
    ax.legend(loc="upper left", fontsize=8)
    return _save(fig, out, "04_weekly_trend.png")


def trial_effect(arms: pd.DataFrame, subgroups: pd.DataFrame, out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={"width_ratios": [1, 1.6]})
    axes[0].bar(
        arms["arm"],
        arms["dna_rate"] * 100,
        yerr=_err(arms),
        color=[GREY, ORANGE],
        error_kw={"ecolor": "black", "capsize": 4},
    )
    for i, r in arms.reset_index(drop=True).iterrows():
        axes[0].text(
            i,
            r["dna_rate"] * 100 / 2,
            f"{r['dna_rate']:.2%}\nn={r['appointments']:,}",
            ha="center",
            color="white",
            fontsize=9,
            fontweight="bold",
        )
    axes[0].set_title("SMS trial: DNA rate by arm (ITT)")
    axes[0].set_ylabel("DNA rate (%)")
    y = np.arange(len(subgroups))
    axes[1].errorbar(
        subgroups["relative_risk"],
        y,
        xerr=[
            subgroups["relative_risk"] - subgroups["rr_low"],
            subgroups["rr_high"] - subgroups["relative_risk"],
        ],
        fmt="o",
        color=ORANGE,
        capsize=3,
    )
    axes[1].axvline(1, color=GREY, linestyle="--")
    axes[1].set_yticks(y, subgroups["subgroup"])
    axes[1].set_xlabel("relative risk of DNA (cost message vs control), 95% CI")
    axes[1].set_title("Relative risk by age band (all point estimates < 1)")
    return _save(fig, out, "05_trial_effect.png")


def odds_ratio_forest(ors: pd.DataFrame, out: Path) -> Path:
    t = ors.sort_values("odds_ratio")
    fig, ax = plt.subplots(figsize=(8, 0.28 * len(t) + 1.2))
    y = np.arange(len(t))
    colours = [
        RED if lo > 1 else (BLUE if hi < 1 else GREY)
        for lo, hi in zip(t["ci_low"], t["ci_high"], strict=True)
    ]
    ax.errorbar(
        t["odds_ratio"],
        y,
        xerr=[t["odds_ratio"] - t["ci_low"], t["ci_high"] - t["odds_ratio"]],
        fmt="none",
        ecolor=GREY,
        capsize=2,
    )
    ax.scatter(t["odds_ratio"], y, color=colours, zorder=3, s=18)
    ax.axvline(1, color="black", linewidth=0.8)
    ax.set_xscale("log")
    ax.set_yticks(y, t["term"])
    ax.set_xlabel("odds ratio (log scale), 95% CI; red = raises DNA risk, blue = lowers")
    ax.set_title("Adjusted drivers of DNA (logistic regression)")
    return _save(fig, out, "06_odds_ratios.png")


def calibration(calib: pd.DataFrame, out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot(calib["predicted"] * 100, calib["observed"] * 100, marker="o", color=BLUE)
    lim = max(calib["predicted"].max(), calib["observed"].max()) * 105
    axes[0].plot([0, lim], [0, lim], color=GREY, linestyle="--")
    axes[0].set_xlabel("predicted DNA rate (%)")
    axes[0].set_ylabel("observed DNA rate (%)")
    axes[0].set_title("Calibration by risk decile (out-of-time test)")
    axes[1].bar(calib["decile"], calib["observed"] * 100, color=ORANGE)
    axes[1].set_xticks(calib["decile"])
    axes[1].set_xlabel("risk decile (10 = highest predicted risk)")
    axes[1].set_ylabel("observed DNA rate (%)")
    lift = calib["observed"].iloc[-1] / calib["observed"].iloc[0]
    axes[1].set_title(f"Lift: riskiest decile DNAs at {lift:.1f}x the lowest")
    return _save(fig, out, "07_calibration_lift.png")


def forecast_backtest(
    series: pd.DataFrame, errors: pd.DataFrame, summary: pd.DataFrame, best: str, out: Path
) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), gridspec_kw={"width_ratios": [1.7, 1]})
    h4 = errors[errors["horizon"] == 4]
    recent = series.loc[series.index >= h4["origin"].min()]
    axes[0].plot(recent.index, recent["dnas"], color="black", label="actual", linewidth=1.5)
    for model, colour in ((best, BLUE), ("naive", GREY)):
        m = h4[h4["model"] == model]
        targets = m["origin"] + pd.Timedelta(weeks=4)
        axes[0].plot(
            targets, m["forecast"], color=colour, marker=".", label=f"{model} (4 wk ahead)"
        )
    axes[0].set_title("Rolling-origin backtest, 4-week-ahead forecasts")
    axes[0].set_ylabel("DNAs per week")
    axes[0].legend(fontsize=8)
    s = summary.sort_values("mae", ascending=False)
    axes[1].barh(s["model"], s["mae"], color=[BLUE if m == best else GREY for m in s["model"]])
    for i, v in enumerate(s["mae"]):
        axes[1].text(v, i, f" {v:.1f}", va="center", fontsize=8)
    axes[1].set_xlabel("MAE (DNAs per week), horizons 1–4")
    axes[1].set_title("Model comparison")
    return _save(fig, out, "08_forecast_backtest.png")


def specialty_heatmap(matrix: pd.DataFrame, out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7, 4.6))
    im = ax.imshow(matrix.to_numpy() * 100, cmap="OrRd", aspect="auto")
    ax.set_xticks(range(matrix.shape[1]), [f"Q{c}" for c in matrix.columns])
    ax.set_yticks(range(matrix.shape[0]), matrix.index)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, f"{matrix.iat[i, j] * 100:.1f}", ha="center", va="center", fontsize=7)
    ax.set_xlabel("IMD quintile (Q1 = most deprived)")
    ax.set_title("DNA rate (%) by specialty and deprivation")
    fig.colorbar(im, ax=ax, shrink=0.8)
    return _save(fig, out, "09_specialty_deprivation_heatmap.png")
