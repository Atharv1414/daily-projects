"""End-to-end analysis ("notebook as a script"): clean → explore → test → model → forecast
→ cost → write findings. Every number in FINDINGS.md comes from this run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from outpatient_dna import charts, forecasting, impact, modelling, segments
from outpatient_dna.cleaning import Dataset, clean, load_raw
from outpatient_dna.config import Paths
from outpatient_dna.stats import (
    TwoProportionResult,
    chi_square,
    power_two_proportions,
    required_n_per_arm,
    srm_check,
    two_proportion_test,
)


@dataclass
class TrialResult:
    itt: TwoProportionResult
    per_protocol: TwoProportionResult
    srm_p: float
    power: float
    n_for_80_power: int
    arms: pd.DataFrame
    subgroups: pd.DataFrame


@dataclass
class Results:
    data: Dataset
    overall_rate: float
    tables: dict[str, pd.DataFrame]
    chi2: dict[str, object]
    trial: TrialResult
    model: modelling.ModelResult
    backtest: forecasting.Backtest
    baseline: dict[str, float]
    scenarios: list[impact.Scenario]
    figures: list[Path] = field(default_factory=list)


def _arm_counts(df: pd.DataFrame) -> tuple[int, int, int, int]:
    g = df.groupby("arm")["dna"].agg(["sum", "count"])
    return (
        int(g.loc["control", "sum"]),
        int(g.loc["control", "count"]),
        int(g.loc["cost_message", "sum"]),
        int(g.loc["cost_message", "count"]),
    )


def analyse_trial(trial: pd.DataFrame) -> TrialResult:
    allocated = trial  # SRM is checked on allocation, before outcomes
    srm_p = srm_check(
        int((allocated["arm"] == "control").sum()), int((allocated["arm"] == "cost_message").sum())
    )
    itt_df = trial[trial["status"].isin(["attended", "dna"])]
    itt = two_proportion_test(*_arm_counts(itt_df))
    pp = two_proportion_test(*_arm_counts(itt_df[itt_df["sms_delivered"]]))
    arms = segments.rate_table(itt_df, "arm")
    rows = []
    for band, g in itt_df.groupby("age_band", observed=True):
        if g["arm"].nunique() == 2 and len(g) > 500:
            r = two_proportion_test(*_arm_counts(g))
            rows.append((f"age {band}", r.relative_risk, *r.rr_ci, len(g)))
    rows.append(("all patients", itt.relative_risk, *itt.rr_ci, len(itt_df)))
    subgroups = pd.DataFrame(rows, columns=["subgroup", "relative_risk", "rr_low", "rr_high", "n"])
    power = power_two_proportions(
        itt.control_rate, itt.treatment_rate, min(itt.n_control, itt.n_treatment)
    )
    n80 = required_n_per_arm(itt.control_rate, itt.treatment_rate)
    return TrialResult(itt, pp, srm_p, power, n80, arms, subgroups)


def run(paths: Paths, make_figures: bool = True) -> Results:
    data = clean(load_raw(paths.data_dir))
    att = data.attendable
    overall = float(att["dna"].mean())
    tables = {
        "specialty": segments.rate_table(att, "specialty"),
        "age_band": segments.rate_table(att, "age_band"),
        "imd_group": segments.rate_table(att, "imd_group"),
        "lead_band": segments.rate_table(att, "lead_band"),
        "contact_mode": segments.rate_table(att, "contact_mode"),
        "weekday": segments.rate_table(att, "weekday"),
        "appointment_type": segments.rate_table(att, "appointment_type"),
        "high_risk": segments.high_risk_profile(att),
    }
    chi2 = {}
    for col in ("specialty", "imd_group", "contact_mode", "weekday"):
        table = pd.crosstab(att[col], att["dna"]).to_numpy()
        chi2[col] = chi_square(table)

    trial = analyse_trial(data.trial)
    model = modelling.fit(att)
    bt = forecasting.backtest(data.appointments)
    baseline = impact.baseline_cost(att, 2025)
    scenarios = [
        impact.sms_rollout(att, trial.itt, 2025),
        impact.targeted_calls(model.test_scored, int(baseline["appointments"])),
    ]
    results = Results(data, overall, tables, chi2, trial, model, bt, baseline, scenarios)

    if make_figures:
        out = paths.figures_dir
        series = forecasting.weekly_series(data.appointments)
        results.figures = [
            charts.rate_bars(
                tables["specialty"],
                "specialty",
                "DNA rate by specialty",
                out,
                "01_specialty.png",
                overall,
            ),
            charts.age_and_deprivation(tables["age_band"], tables["imd_group"], out),
            charts.lead_time(tables["lead_band"], out),
            charts.weekly_trend(series, out),
            charts.trial_effect(trial.arms, trial.subgroups, out),
            charts.odds_ratio_forest(model.odds_ratios, out),
            charts.calibration(model.calibration, out),
            charts.forecast_backtest(series, bt.errors, bt.summary, bt.best_model, out),
            charts.specialty_heatmap(segments.specialty_imd_matrix(att), out),
        ]
    return results


def headline(results: Results) -> dict[str, float | str]:
    t = results.trial.itt
    ors = results.model.odds_ratios.set_index("term")["odds_ratio"]
    sms, calls = results.scenarios
    naive_mae = float(results.backtest.summary.set_index("model").loc["naive", "mae"])
    best = results.backtest.summary.iloc[0]
    return {
        "dna_rate": results.overall_rate,
        "dnas_2025": results.baseline["dnas"],
        "cost_2025": results.baseline["cost_gbp"],
        "trial_control": t.control_rate,
        "trial_treatment": t.treatment_rate,
        "trial_rrr": t.relative_reduction,
        "trial_p": t.p_value,
        "trial_nnt": t.nnt,
        "auc_test": results.model.auc_test,
        "top_decile_capture": results.model.top_decile_capture,
        "or_age_18_29": float(ors.get("age: 18-29", np.nan)),
        "or_prior_dna_3": float(ors.get("prior DNAs: 3", np.nan)),
        "sms_saving": sms.net_saving_gbp,
        "calls_net": calls.net_saving_gbp,
        "best_forecast": str(best["model"]),
        "best_mae": float(best["mae"]),
        "mae_vs_naive": 1 - float(best["mae"]) / naive_mae,
    }
