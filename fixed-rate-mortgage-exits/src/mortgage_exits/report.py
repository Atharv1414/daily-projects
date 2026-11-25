"""Runs the whole study and writes FINDINGS.md, so every number in it comes from the run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from mortgage_exits import charts, evaluation, hazards, survival, value
from mortgage_exits.cleaning import CleaningLog, build_study
from mortgage_exits.config import LABELS, LEFT, Economics, Study
from mortgage_exits.datagen import RawData


@dataclass
class Results:
    data: pd.DataFrame
    log: CleaningLog
    panel: pd.DataFrame
    aj: pd.DataFrame
    naive: dict[int, np.ndarray]
    no_entry: pd.DataFrame
    curves: dict[str, pd.DataFrame]
    ratios: pd.DataFrame
    broker_gap: tuple[float, float, float]
    test: evaluation.Backtest
    gains: pd.DataFrame
    tenths: pd.DataFrame
    sensitivity: pd.DataFrame


def analyse(raw: RawData, study: Study, economics: Economics) -> Results:
    data, rates, log = build_study(raw, study)
    entry, exit_, cause, months = data["entry"], data["exit"], data["cause"], study.max_month
    panel = hazards.person_months(data, rates, study)
    test = evaluation.backtest(data, rates, study)
    broker = data["channel"] == "Broker"
    return Results(
        data=data,
        log=log,
        panel=panel,
        aj=survival.aalen_johansen(entry, exit_, cause, months),
        naive={k: survival.naive_one_minus_km(entry, exit_, cause, months, k) for k in LABELS},
        no_entry=survival.aalen_johansen(entry * 0, exit_, cause, months),
        curves={
            str(name): survival.aalen_johansen(p["entry"], p["exit"], p["cause"], months)
            for name, p in data.groupby("shock_group", observed=True)
        },
        ratios=hazards.fit(panel, hazards.EXPLAIN).hazard_ratios(),
        broker_gap=survival.bootstrap_difference(
            data, broker, ~broker, LEFT, months, study.bootstrap, study.seed
        ),
        test=test,
        gains=value.gains(test.predictions, economics),
        tenths=value.break_even(test.predictions, economics),
        sensitivity=value.sensitivity(test.predictions, economics),
    )


def draw(r: Results, economics: Economics, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    return [
        charts.destinations(r.aj, folder / "1_destinations.png"),
        charts.naive_gap(r.aj, r.naive, folder / "2_naive_gap.png"),
        charts.by_shock(r.curves, folder / "3_payment_rise.png"),
        charts.timing(r.panel, folder / "4_timing.png"),
        charts.forest(r.ratios, folder / "5_hazard_ratios.png"),
        charts.calibration(r.test.calibration, folder / "6_calibration.png"),
        charts.gains(r.gains, folder / "7_gains.png"),
        charts.break_even(r.tenths, economics.save_rate, folder / "8_break_even.png"),
    ]


def _table(frame: pd.DataFrame, formats: dict[str, str]) -> str:
    head = "| " + " | ".join(formats) + " |\n|" + "---|" * len(formats)
    rows = [
        "| "
        + " | ".join(fmt.format(v) for fmt, v in zip(formats.values(), row, strict=True))
        + " |"
        for row in frame.itertuples(index=False)
    ]
    return head + "\n" + "\n".join(rows)


def summary(r: Results, study: Study) -> dict:
    end = r.aj[r.aj["month"] == study.max_month].set_index("cause")
    scores = r.test.scores.set_index("model")
    at20 = r.gains[np.isclose(r.gains["share"], 0.2)].set_index("ranking")["reached"]
    return {
        "mortgages": len(r.data),
        "person_months": len(r.panel),
        "left": float(end.loc[LEFT, "cif"]),
        "left_low": float(end.loc[LEFT, "low"]),
        "left_high": float(end.loc[LEFT, "high"]),
        "left_naive": float(r.naive[LEFT][-1]),
        "stayed": float(end.loc[1, "cif"]),
        "left_before_fix_ends": float(survival.cif_at(r.aj, LEFT, study.lead_months)["cif"]),
        "broker_gap": r.broker_gap,
        "brier": scores["brier"].to_dict(),
        "auc": float(scores.loc["Competing-risks model", "auc"]),
        "reached_at_20": at20.to_dict(),
    }


def findings(r: Results, study: Study, economics: Economics) -> str:
    s = summary(r, study)
    h = study.max_month
    hr = r.ratios.set_index(["cause", "feature"])
    shock = np.exp(0.25 * hr.loc[(LEFT, "shock"), "log_hr"])
    shock_low, shock_high = (
        np.exp(0.25 * (hr.loc[(LEFT, "shock"), "log_hr"] + z * hr.loc[(LEFT, "shock"), "se"]))
        for z in (-1.96, 1.96)
    )
    arrears = np.exp(0.25 * hr.loc[(4, "shock"), "log_hr"])
    groups = {k: survival.cif_at(v, LEFT, h)["cif"] for k, v in r.curves.items()}
    first, last = list(groups.items())[0], list(groups.items())[-1]
    entry_gap = survival.cif_at(r.no_entry, 1, h)["cif"] - survival.cif_at(r.aj, 1, h)["cif"]
    scores = r.test.scores
    model = scores[scores["model"] == "Competing-risks model"].iloc[0]
    logit = scores[scores["model"].str.startswith("Finished")].iloc[0]
    diff = r.test.differences.set_index("versus")
    top, bottom = r.tenths.iloc[0], r.tenths.iloc[-1]
    g = s["reached_at_20"]
    end = r.aj[r.aj["month"] == h][["cause", "cif", "low", "high"]].copy()
    end["cause"] = end["cause"].map(LABELS)
    end["naive"] = [r.naive[k][-1] for k in LABELS]
    cleaning = _table(r.log.frame(), {"Rule": "{}", "Rows": "{:,}"})
    ends = _table(
        end,
        {
            "Exit": "{}",
            "Share": "{:.1%}",
            "Low": "{:.1%}",
            "High": "{:.1%}",
            "Wrongly, as 1-KM": "{:.1%}",
        },
    )
    score = _table(
        scores[["model", "brier", "brier_low", "brier_high", "auc", "mean_predicted", "observed"]],
        {
            "Forecast": "{}",
            "Brier": "{:.4f}",
            "Low": "{:.4f}",
            "High": "{:.4f}",
            "AUC": "{:.3f}",
            "Mean forecast": "{:.1%}",
            "Observed": "{:.1%}",
        },
    )
    gap = _table(
        r.test.differences,
        {"Model beats": "{}", "Brier gain": "{:.4f}", "Low": "{:.4f}", "High": "{:.4f}"},
    )
    tenth = _table(
        r.tenths,
        {
            "Tenth": "{}",
            "Accounts": "{:,}",
            "Left": "{:.0%}",
            "Margin lost each": "£{:,.0f}",
            "Break-even save rate": "{:.1%}",
            "Net per call, £": "{:,.0f}",
        },
    )
    sens = _table(
        r.sensitivity,
        {
            "Save rate": "{:.0%}",
            "Calls": "{:,}",
            "Net, planned calls, £": "{:,.0f}",
            "Net, call everyone, £": "{:,.0f}",
        },
    )
    return f"""# Findings

{s["mortgages"]:,} mortgages and {s["person_months"]:,} months at risk. Synthetic data.

## 1. {s["left"]:.0%} remortgage elsewhere within {h} months, not {s["left_naive"]:.0%}

{ends}

Treating the other exits as missing data answers a question nobody asked: how many would leave if taking a new deal, selling and arrears were impossible.

![Destinations](figures/1_destinations.png)

![The error from ignoring competing risks](figures/2_naive_gap.png)

## 2. {s["left_before_fix_ends"] / s["left"]:.0%} of those who leave have gone before the fix ends

{s["left_before_fix_ends"]:.1%} of all mortgages leave inside the six-month window. A letter sent on the day the fix ends reaches none of them.

![Timing](figures/4_timing.png)

## 3. People facing bigger payment rises leave more

{first[1]:.0%} of those whose payment would not rise leave, against {last[1]:.0%} of those facing a rise of over 40%. With other factors held still, each 25% rise multiplies the monthly chance of leaving by {shock:.2f} ({shock_low:.2f} to {shock_high:.2f}), and of arrears by {arrears:.2f}.

![By payment rise](figures/3_payment_rise.png)

## 4. Broker customers leave more

{100 * s["broker_gap"][0]:+.1f} points ({100 * s["broker_gap"][1]:+.1f} to {100 * s["broker_gap"][2]:+.1f}) compared with direct customers, unadjusted. This is an association. Customers choose how they apply.

![Hazard ratios](figures/5_hazard_ratios.png)

## 5. The forecast holds up, and beats the quick model

Built on {r.test.train_rows:,} mortgages as they stood on {study.split:%d %B %Y}, and marked on {r.test.test_rows:,} whose clocks started later. Forecast: leaving within {study.horizon} months.

{score}

{gap}

Ranking is the same as a logistic regression on finished cases (AUC {model["auc"]:.3f} against {logit["auc"]:.3f}). The gain is in the level: that regression forecasts {logit["mean_predicted"]:.0%} on average and {logit["observed"]:.0%} happened, because dropping unfinished cases drops people who stayed. The gain in Brier score is {diff.loc[logit["model"], "gain"]:.4f} ({diff.loc[logit["model"], "low"]:.4f} to {diff.loc[logit["model"], "high"]:.4f}).

![Calibration](figures/6_calibration.png)

## 6. Rank calls by chance times balance

With time to call one customer in five, chance times balance reaches {g["Chance x balance"]:.0%} of the margin that was lost. Balance alone reaches {g["Balance only"]:.0%} and chance alone {g["Chance only"]:.0%}. Most of the benefit comes from the balance, which is free.

![Gains](figures/7_gains.png)

{tenth}

![Break-even](figures/8_break_even.png)

The top tenth pays for itself if {top["break_even_save_rate"]:.1%} of would-be leavers are kept. The bottom tenth needs {bottom["break_even_save_rate"]:.1%}.

{sens}

## Recommendations

1. **Start at month 1, not at the end of the fix.** {s["left_before_fix_ends"] / s["left"]:.0%} of the loss is over by then.
2. **Work down the chance-times-balance list** as far as call time allows. If time is unlimited and calls save {economics.save_rate:.0%}, the model adds little over calling everyone, as the last table shows.
3. **Run it as a randomised trial.** The save rate is an assumption ({economics.save_rate:.0%}). A control group is the only way to learn it.
4. **Send large payment rises to the affordability team first.** The same customers are most likely to fall into arrears, so a sales call alone is the wrong first contact.
5. **Stop reporting 1 minus Kaplan-Meier.** It overstates losses by {100 * (s["left_naive"] - s["left"]):.0f} percentage points.

## Caveats

- Hazard ratios are associations. The data are simulated, so they can be checked against the truth, and the tests do that. Real data would have confounders nobody wrote down.
- Delayed entry moved the share taking a new deal by {100 * entry_gap:+.1f} points when ignored. That is small here because only {(r.data["entry"] > 0).mean():.0%} of mortgages were acquired.
- The forecast uses the market rate on day one. If rates move sharply, calibration will drift.
- Economics: {economics.net_margin:.2%} margin a year for {economics.kept_years:g} years, £{economics.call_cost:g} a call. Change them in `config.py`.

## Cleaning log

{cleaning}
"""  # noqa: E501


def write(r: Results, study: Study, economics: Economics, folder: Path) -> Path:
    draw(r, economics, folder / "figures")
    (folder / "summary.json").write_text(json.dumps(summary(r, study), indent=2) + "\n")
    path = folder / "FINDINGS.md"
    path.write_text(findings(r, study, economics))
    return path
