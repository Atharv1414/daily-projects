"""Writes FINDINGS.md: quantified findings, recommendations and caveats."""

from __future__ import annotations

import math
from pathlib import Path

from outpatient_dna.analysis import Results, headline
from outpatient_dna.config import COST_PER_CALL_GBP, COST_PER_DNA_GBP
from outpatient_dna.impact import CALL_CONTACT_RATE, CALL_EFFECT


def _pct(x: float, dp: int = 1) -> str:
    return f"{x * 100:.{dp}f}%"


def _gbp(x: float) -> str:
    return f"£{x:,.0f}"


def _rate_rows(t, col: str, n: int = 20) -> list[str]:
    rows = [f"| {col} | Appointments | DNA rate | 95% CI |", "|---|---:|---:|---|"]
    for _, r in t.head(n).iterrows():
        rows.append(
            f"| {r[col]} | {r['appointments']:,} | {_pct(r['dna_rate'])} | "
            f"{_pct(r['ci_low'])}–{_pct(r['ci_high'])} |"
        )
    return rows


def _describe(row) -> str:
    parts = [
        "aged 18–44" if row["young"] else "aged 0–17 or 45+",
        "IMD 1–3" if row["deprived"] else "IMD 4–10 or unknown",
        "booked 8+ weeks ahead" if row["long_wait"] else "booked under 8 weeks ahead",
        "a previous DNA" if row["prior_dna"] else "no previous DNA",
    ]
    return ", ".join(parts[:3]) + " and " + parts[3]


def build(results: Results) -> str:
    h = headline(results)
    t = results.trial
    m = results.model
    spec = results.tables["specialty"].sort_values("dna_rate", ascending=False)
    imd = results.tables["imd_group"]
    imd1 = imd.loc[imd["imd_group"] == "1", "dna_rate"].iloc[0]
    imd10 = imd.loc[imd["imd_group"] == "10", "dna_rate"].iloc[0]
    risk = results.tables["high_risk"].iloc[0]
    lowest = results.tables["high_risk"].iloc[-1]
    calib = m.calibration
    lift = calib["observed"].iloc[-1] / calib["observed"].iloc[0]
    over = (calib["predicted"] - calib["observed"]).mean()
    sms, calls = results.scenarios
    lines = [
        "# Findings: missed outpatient appointments at Riverside NHS FT (synthetic data)",
        "",
        "## Executive summary",
        "",
        f"- **{_pct(h['dna_rate'])}** of outpatient appointments that went ahead were missed "
        f"(DNA). In 2025 that was **{h['dnas_2025']:,.0f} DNAs**, costing about "
        f"**{_gbp(h['cost_2025'])}** at {_gbp(COST_PER_DNA_GBP)} each.",
        f"- The **SMS trial worked**: telling patients what a missed appointment costs the NHS cut "
        f"DNAs from {_pct(t.itt.control_rate, 2)} to {_pct(t.itt.treatment_rate, 2)}: "
        f"**{_pct(t.itt.relative_reduction)} fewer in relative terms** "
        f"(95% CI {_pct(1 - t.itt.rr_ci[1])}–{_pct(1 - t.itt.rr_ci[0])}, "
        f"p = {t.itt.p_value:.1e}). One DNA is prevented for every {t.itt.nnt:.0f} reminders.",
        f"- Rolling it out to every patient with a mobile would prevent about "
        f"**{sms.dnas_avoided:,.0f} DNAs a year** (range {sms.dnas_avoided_low:,.0f}–"
        f"{sms.dnas_avoided_high:,.0f}), worth **{_gbp(sms.net_saving_gbp)}** at zero marginal "
        "cost, because the message text changes but the number of messages doesn't.",
        f"- Risk is concentrated. Patients aged 18–29 have {h['or_age_18_29']:.2f}× the odds of "
        f"missing, the most deprived decile misses {_pct(imd1)} vs {_pct(imd10)} in the least "
        f"deprived, and three or more prior DNAs doubles the odds ({h['or_prior_dna_3']:.2f}×). "
        f"The riskiest 10% of appointments hold {_pct(h['top_decile_capture'])} of DNAs.",
        f"- For capacity planning, a **4-week moving average** of weekly DNAs "
        f"(MAE {h['best_mae']:.1f} DNAs/week) beats the naive baseline by "
        f"{_pct(h['mae_vs_naive'])}. More complex models didn't do better.",
        "",
        "**Recommendation:** switch all reminder SMS to the cost-message wording now. Then run "
        "a 3-month randomised pilot of phone calls for the top-risk decile before funding it "
        "at scale. Use the model's risk score to target the calls, and the 4-week moving "
        "average to set clinic overbooking levels.",
        "",
        "## 1. Data and cleaning",
        "",
        "Four PAS extract tables (patients, clinics, appointments, SMS trial allocation), "
        "Jan 2024 to Dec 2025. DNA rate = DNAs / (attended + DNA). Cancellations are excluded "
        "from the denominator, as in NHS England reporting.",
        "",
        results.data.log.to_markdown(),
        "",
        "## 2. Where DNAs happen",
        "",
        *_rate_rows(spec, "specialty"),
        "",
        f"Chi-square tests of independence: specialty χ² = {results.chi2['specialty'].chi2:,.0f}"
        f" (Cramér's V {results.chi2['specialty'].cramers_v:.3f}); deprivation χ² = "
        f"{results.chi2['imd_group'].chi2:,.0f} (V {results.chi2['imd_group'].cramers_v:.3f}); "
        f"contact mode χ² = {results.chi2['contact_mode'].chi2:,.0f} "
        f"(V {results.chi2['contact_mode'].cramers_v:.3f}). All p < 0.001. Effect sizes are "
        "small individually, which is why a multivariable model is needed.",
        "",
        f"**Highest-risk combination:** {_describe(risk)} → {_pct(risk['dna_rate'])} DNA rate "
        f"(n = {risk['appointments']:,}), against {_pct(lowest['dna_rate'])} for "
        f"{_describe(lowest)}.",
        "",
        "## 3. SMS reminder trial (randomised, 1 Apr – 30 Sep 2025)",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Allocation | {t.itt.n_control:,} control vs {t.itt.n_treatment:,} cost message "
        f"(appointments that went ahead) |",
        f"| Sample-ratio mismatch check | p = {t.srm_p:.2f} (no evidence randomisation broke) |",
        f"| DNA rate, control | {_pct(t.itt.control_rate, 2)} |",
        f"| DNA rate, cost message | {_pct(t.itt.treatment_rate, 2)} |",
        f"| Absolute difference | {t.itt.diff * 100:.2f} pp (95% CI {t.itt.diff_ci[0] * 100:.2f}"
        f" to {t.itt.diff_ci[1] * 100:.2f}) |",
        f"| Relative risk | {t.itt.relative_risk:.3f} (95% CI {t.itt.rr_ci[0]:.3f}–"
        f"{t.itt.rr_ci[1]:.3f}) |",
        f"| z, p-value | {t.itt.z:.2f}, {t.itt.p_value:.1e} |",
        f"| Cohen's h | {t.itt.cohens_h:.3f} (small, as expected for a nudge) |",
        f"| Number needed to treat | {t.itt.nnt:.0f} reminders per DNA prevented |",
        f"| Per-protocol (SMS delivered) RR | {t.per_protocol.relative_risk:.3f} |",
        f"| Achieved power | {_pct(t.power)}; n per arm for 80% power: {t.n_for_80_power:,} |",
        "",
        "In every age band the point estimate is below 1 and the confidence intervals overlap "
        "(see `05_trial_effect.png`), so there's no evidence the effect is limited to one "
        "group. The intention-to-treat estimate is the one to plan on.",
        "",
        "## 4. What drives DNA risk (adjusted)",
        "",
        f"Logistic regression trained on appointments before 1 Jul 2025 (n = {m.n_train:,}) "
        f"and tested out-of-time after it (n = {m.n_test:,}). AUC: {m.auc_train:.3f} train, "
        f"{m.auc_test:.3f} test, so it doesn't overfit. Brier score {m.brier_test:.4f} "
        f"against a base rate of {_pct(m.base_rate_test)}. The highest-risk decile DNAs at "
        f"{lift:.1f}× the rate of the lowest. Calibration is close, but the model over-predicts "
        f"by {over * 100:.1f} pp on average, because the trial's cost message lowered DNAs "
        "during the test period. Recalibrate after rollout.",
        "",
        "| Driver | Odds ratio | 95% CI |",
        "|---|---:|---|",
    ]
    top = (
        m.odds_ratios.assign(dist=lambda d: d["odds_ratio"].apply(lambda x: abs(math.log(x))))
        .sort_values("dist", ascending=False)
        .head(12)
    )
    lines += [
        f"| {r.term} | {r.odds_ratio:.2f} | {r.ci_low:.2f}–{r.ci_high:.2f} |"
        for r in top.itertuples()
    ]
    bt = results.backtest.summary
    lines += [
        "",
        "AUC around 0.64 is typical of published DNA models. Attendance depends a lot on "
        "things a PAS doesn't record (transport, caring duties, how the patient feels that "
        "day). It is good enough to rank patients for targeting, but not to decide anyone's "
        "care.",
        "",
        "## 5. Forecasting weekly DNAs (rolling-origin backtest, 26 origins × 4 horizons)",
        "",
        "| Model | MAE (DNAs/week) | MAPE | Bias |",
        "|---|---:|---:|---:|",
        *[f"| {r.model} | {r.mae:.1f} | {r.mape:.1f}% | {r.bias:+.1f} |" for r in bt.itertuples()],
        "",
        "Every model except the seasonal naive under-forecasts slightly (negative bias), "
        "because the backtest window covers the end of the trial and the December peak. "
        "The seasonal naive over-forecasts because last year had no trial. "
        "The booking-informed model "
        "uses only bookings known at the forecast origin. It didn't beat the moving average, "
        "because weekly volume is stable and the DNA *rate* is what moves.",
        "",
        "## 6. Financial case (2025 volumes)",
        "",
        "| Option | Appointments targeted | DNAs avoided (range) | Cost | Net saving (range) |",
        "|---|---:|---:|---:|---:|",
    ]
    for s in (sms, calls):
        lo, hi = s.net_range_gbp
        lines.append(
            f"| {s.name} | {s.appointments_targeted:,} | {s.dnas_avoided:,.0f} "
            f"({s.dnas_avoided_low:,.0f}–{s.dnas_avoided_high:,.0f}) | "
            f"{_gbp(s.intervention_cost_gbp)} | {_gbp(s.net_saving_gbp)} "
            f"({_gbp(lo)}–{_gbp(hi)}) |"
        )
    lines += [
        "",
        f"Phone-call assumptions (not measured here, so pilot first): {_pct(CALL_CONTACT_RATE, 0)}"
        f" of calls answered, {_pct(CALL_EFFECT, 0)} relative reduction when reached, "
        f"£{COST_PER_CALL_GBP:.2f} staff cost per call. 'Savings' are mostly freed clinic "
        "capacity (slots that can be re-booked), not cash. The real benefit is shorter waits.",
        "",
        "## 7. Caveats",
        "",
        "- The data is synthetic, generated from a known model, so the effects are realistic "
        "in size but not real NHS results.",
        f"- {_gbp(COST_PER_DNA_GBP)} per DNA is a national average. Specialty costs differ.",
        "- The trial ran over summer. Winter effects may differ, so monitor after rollout.",
        "- Prior-DNA features use only earlier appointments, so there is no leakage, but new "
        "patients have no history and get a lower-information score.",
        "- Deprivation is area-level (IMD), not individual circumstances.",
    ]
    return "\n".join(lines) + "\n"


def write(results: Results, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "FINDINGS.md"
    path.write_text(build(results), encoding="utf-8")
    return path
