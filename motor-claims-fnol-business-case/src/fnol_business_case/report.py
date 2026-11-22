"""Assemble the business case: run analysis and model, write charts and markdown documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from fnol_business_case import analysis, charts, finance, process, requirements, risks
from fnol_business_case import stakeholders as sh
from fnol_business_case.datagen import GenConfig, generate_claims

DATA = Path(__file__).resolve().parents[2] / "data"


@dataclass
class CaseResults:
    claims: pd.DataFrame
    cleaning: analysis.CleaningLog
    baseline: dict[str, float]
    comparisons: list[analysis.Comparison]
    did: analysis.DiDResult
    rental: analysis.RentalLink
    assumptions: finance.Assumptions
    metrics: finance.Metrics
    cash_flow: pd.DataFrame
    tornado: pd.DataFrame
    scenarios: pd.DataFrame
    monte_carlo: finance.MonteCarlo
    break_even_adoption: float
    break_even_days: float
    stories: list[requirements.Story]
    backlog_issues: list[requirements.BacklogIssue]
    people: list[sh.Stakeholder]
    raci: dict[str, dict[str, str]]
    raci_findings: list[sh.RaciFinding]
    processes: dict[str, process.Process]
    process_metrics: dict[str, process.ProcessMetrics]
    risks: list[risks.Risk]
    extra: dict[str, Any] = field(default_factory=dict)


def run(
    data_dir: Path = DATA, cfg: GenConfig | None = None, n_boot: int = 1_000, n_sims: int = 10_000
) -> CaseResults:
    claims, log = analysis.clean(generate_claims(cfg or GenConfig()))
    base = analysis.baseline(claims)
    comps = analysis.channel_comparison(claims)
    did = analysis.difference_in_differences(claims, n_boot=n_boot)
    rental = analysis.rental_vs_cycle(claims)
    handle = next(c for c in comps if c.metric == "FNOL handle minutes")
    assumptions = finance.from_evidence(
        base,
        (did.per_digital_claim, *did.per_digital_ci),
        (handle.difference, handle.ci_low, handle.ci_high),
        rental.slope_rental_days_per_cycle_day,
    )
    v = finance.values(assumptions)
    stories = requirements.load_backlog(data_dir / "backlog.json")
    people, raci = sh.load(data_dir / "stakeholders.json")
    procs = process.load(data_dir / "processes.json")
    return CaseResults(
        claims,
        log,
        base,
        comps,
        did,
        rental,
        assumptions,
        finance.evaluate(v),
        finance.cash_flow_table(v),
        finance.tornado(assumptions),
        finance.scenarios(assumptions),
        finance.monte_carlo(assumptions, n=n_sims),
        finance.break_even(assumptions, "target_adoption", 0.01, 0.95),
        finance.break_even(assumptions, "cycle_days_saved", 0.0, 10.0),
        stories,
        requirements.validate_backlog(stories),
        people,
        raci,
        sh.analyse_raci(people, raci),
        procs,
        {k: process.metrics(p) for k, p in procs.items()},
        risks.load(data_dir / "risks.json"),
    )


def gbp(v: float) -> str:
    sign = "-" if v < 0 else ""
    v = abs(v)
    return f"{sign}£{v / 1e6:,.2f}m" if v >= 1e6 else f"{sign}£{v:,.0f}"


def pct(v: float, signed: bool = False) -> str:
    if pd.isna(v) or v in (float("inf"), float("-inf")):
        return "n/a"
    return f"{v:+.1%}" if signed else f"{v:.1%}"


def years(v: float) -> str:
    return "never" if v == float("inf") else f"{v:.1f} yrs"


def write_charts(r: CaseResults, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    scen = {}
    for label, favourable in (("Pessimistic", False), ("Base", None), ("Optimistic", True)):
        v = (
            finance.values(r.assumptions)
            if favourable is None
            else {
                k: (a.high if a.higher_is_better == favourable else a.low)
                for k, a in r.assumptions.items()
            }
        )
        scen[label] = finance.cash_flows(v)["net"]
    return [
        charts.channel_mix(r.claims, out),
        charts.did_trend(r.claims, out),
        charts.comparison(r.comparisons, out),
        charts.hire_vs_cycle(r.claims, r.rental.slope_rental_days_per_cycle_day, out),
        charts.tornado_chart(r.tornado, out),
        charts.monte_carlo_chart(r.monte_carlo, out),
        charts.cumulative_cash(scen, out),
        charts.power_interest(r.people, out),
        charts.risk_heatmap(r.risks, out),
    ]


def business_case_md(r: CaseResults) -> str:
    m, b, d, mc = r.metrics, r.baseline, r.did, r.monte_carlo
    cur, fut = r.process_metrics["current"], r.process_metrics["future"]
    top = r.tornado.iloc[0]
    sc = r.scenarios
    cf = r.cash_flow.copy()
    cf_md = ["| Line | " + " | ".join(cf.columns) + " |", "|---|" + "---|" * len(cf.columns)]
    for idx, row in cf.iterrows():
        cf_md.append(
            f"| {idx} | " + " | ".join("" if pd.isna(x) else f"{x:,.0f}" for x in row) + " |"
        )
    assumptions_md = [
        "| Assumption | Low | Base | High | Unit | Source |",
        "|---|---|---|---|---|---|",
    ]
    for a in r.assumptions.values():
        assumptions_md.append(
            f"| {a.label} | {a.low:,.3g} | {a.base:,.4g} | {a.high:,.3g} | {a.unit} | {a.source} |"
        )
    comp_md = [
        "| Metric (simple claims) | Digital | Phone | Difference (95% CI) | p | Cohen's d |",
        "|---|---|---|---|---|---|",
    ]
    for c in r.comparisons:
        comp_md.append(
            f"| {c.metric} | {c.digital_mean:.2f} | {c.phone_mean:.2f} | "
            f"{c.difference:+.2f} ({c.ci_low:+.2f} to {c.ci_high:+.2f}) | "
            f"{c.p_value:.1g} | {c.cohens_d:.2f} |"
        )
    raci_gaps = [f for f in r.raci_findings if f.severity != "error"]
    must_pts = sum(s.points for s in r.stories if s.moscow == "Must")
    scope_pts = sum(s.points for s in r.stories if s.moscow != "Won't")
    return f"""# Business case: Digital FNOL for motor claims

*Albion Mutual (fictional UK motor insurer) · prepared for the Claims Investment Committee ·
all figures generated by `fnol-case report` from seeded data.*

## 1. Executive summary

**Recommendation: approve a phased national rollout of digital first notification of loss
(FNOL), with a stage-gate at month 6 on digital adoption (break-even {pct(r.break_even_adoption)}).**

- **Problem.** {pct(b["phone_share"])} of {b["annual_claims"]:,.0f} annual claims are reported
  by phone ({b["phone_handle_minutes"]:.1f} min per call). Claims take
  {b["mean_days_to_settle"]:.1f} days on average to settle, and hire cars run for the whole
  cycle: {pct(b["rental_share"])} of claims have one, costing {gbp(b["total_rental_cost"])} a year.
  Claimant NPS is {b["nps"]:.0f}.
- **Evidence.** A digital FNOL pilot in two regions cut mean settlement time by
  **{-d.estimate:.2f} days per claim** against control regions (difference-in-differences,
  95% CI {-d.ci_high:.2f} to {-d.ci_low:.2f}). With {pct(d.digital_share_post)} take-up, that is
  **≈{-d.per_digital_claim:.1f} days per digital claim**. Digital FNOL also takes
  {-r.comparisons[0].difference:.0f} fewer handler minutes.
- **Value.** Over 5 years, NPV is **{gbp(m.npv)}** at 8%, IRR is **{pct(m.irr)}**, payback is
  **{years(m.payback)}** (discounted {years(m.discounted_payback)}) and ROI is {pct(m.roi)}.
  Benefits total {gbp(m.total_benefits)} against costs of {gbp(m.total_costs)}.
- **Risk.** In {len(mc.npvs):,} Monte Carlo runs, **NPV is positive in {pct(mc.p_positive)}**
  (P10 {gbp(mc.p10)}, P50 {gbp(mc.p50)}, P90 {gbp(mc.p90)}). The case is most sensitive to
  *{top.assumption}*. If every assumption lands at its unfavourable end at once, NPV is
  {gbp(sc.loc["Pessimistic", "NPV"])}. That is why the rollout is gated.
- **Process.** Expected FNOL-to-repair-booking lead time falls from {cur.lead_time_hours:.0f} h
  to {fut.lead_time_hours:.0f} h, process cycle efficiency rises from
  {pct(cur.process_cycle_efficiency)} to {pct(fut.process_cycle_efficiency)}, and handoffs fall
  from {cur.handoffs:.0f} to {fut.handoffs:.1f}.

## 2. Current state analysis

![Channel mix](charts/01_channel_mix.png)

12 months before the pilot (May 2025 – Apr 2026):

| KPI | Value |
|---|---|
| Claims notified | {b["annual_claims"]:,.0f} |
| Phone share | {pct(b["phone_share"])} |
| Phone FNOL handle time | {b["phone_handle_minutes"]:.1f} min |
| Mean / median days to settle | {b["mean_days_to_settle"]:.1f} / {b["median_days_to_settle"]:.0f} |
| Claims with a hire car | {pct(b["rental_share"])} (mean {b["mean_rental_days"]:.1f} days at £{b["rental_cost_per_day"]:.2f}/day) |
| Annual hire-car cost | {gbp(b["total_rental_cost"])} |
| Mean indemnity (excl. total loss) | £{b["mean_indemnity"]:,.0f} |
| Complaint rate | {pct(b["complaint_rate"])} |
| Claimant NPS | {b["nps"]:.0f} |

Cleaning log: {"; ".join(f"{s}: {n:,}" for s, n in r.cleaning.steps)}.

![Hire vs cycle](charts/04_hire_vs_cycle.png)

Each extra day of cycle time adds **{r.rental.slope_rental_days_per_cycle_day:.2f} hire-car
days** (OLS, R² = {r.rental.r_squared:.2f}, n = {r.rental.n:,}). This is the link that turns
faster FNOL into cash.

## 3. Pilot evaluation

![DiD](charts/02_did_cycle_time.png)

| Cell | Mean days to settle |
|---|---|
| Pilot regions, pre (Nov 25–Apr 26) | {d.cells["pilot_pre"]:.2f} |
| Pilot regions, post (May–Aug 26) | {d.cells["pilot_post"]:.2f} |
| Control regions, pre | {d.cells["control_pre"]:.2f} |
| Control regions, post | {d.cells["control_post"]:.2f} |
| **Difference-in-differences** | **{d.estimate:+.2f}** (95% CI {d.ci_low:+.2f} to {d.ci_high:+.2f}) |

The pre-launch gap between pilot and control regions is flat (slope {d.pre_trend_slope:+.3f}
days/month, p = {d.pre_trend_p:.2f}), which supports the parallel-trends assumption. Post-launch
claims are cut off at 22 Aug 2026, so most have settled by the data date. The claim-level
comparison below is observational (customers chose the channel), so it is used only for handle
time, which the channel itself determines.

![Digital vs phone](charts/03_digital_vs_phone.png)

{chr(10).join(comp_md)}

## 4. Process: current vs future state

Current state: {cur.steps} steps, {cur.handoffs:.0f} handoffs, lead time {cur.lead_time_hours:.0f} h,
touch time {cur.touch_time_min:.0f} min, PCE {pct(cur.process_cycle_efficiency)}. Red = non-value-adding.

```mermaid
{process.mermaid(r.processes["current"])}
```

Future state (expected values with {pct(r.processes["future"].simple_share or 0)} of digital
claims routed straight through): lead time {fut.lead_time_hours:.0f} h, touch time
{fut.touch_time_min:.0f} min, PCE {pct(fut.process_cycle_efficiency)}.

```mermaid
{process.mermaid(r.processes["future"])}
```

## 5. Stakeholders and RACI

![Stakeholder map](charts/08_stakeholder_map.png)

{sh.register_markdown(r.people)}

{sh.raci_markdown(r.people, r.raci)}

**RACI gap analysis** (automated checks: one Accountable per activity, at least one
Responsible, high-power stakeholders included in go-live):

{chr(10).join(f"- **{f.activity}**: {f.message}" for f in raci_gaps) or "- No gaps."}

*Action:* name Responsible owners (a product owner, an IT delivery lead and a DPIA analyst)
before mobilisation.

## 6. Requirements

{len(r.stories)} user stories across {len({s.epic for s in r.stories})} epics, prioritised with
MoSCoW then WSJF. Musts are {must_pts} of {scope_pts} in-scope points
({must_pts / scope_pts:.0%}). Every story has Gherkin acceptance criteria. The full backlog is
in [BACKLOG.md](BACKLOG.md) and the executable `.feature` files are in [features/](features/).

Backlog checks: {"; ".join(f"{i.severity}: {i.message}" for i in r.backlog_issues) or "none"}.

## 7. Financial case

Key assumptions (data-backed where possible; ranges drive the sensitivity analysis):

{chr(10).join(assumptions_md)}

5-year cash flow, base case (£):

{chr(10).join(cf_md)}

| Scenario | NPV | IRR | Payback | Discounted payback | ROI |
|---|---|---|---|---|---|
{chr(10).join(f"| {i} | {gbp(row['NPV'])} | {pct(row['IRR'])} | {years(row['Payback (yrs)'])} | {years(row['Discounted payback (yrs)'])} | {pct(row['ROI'])} |" for i, row in sc.iterrows())}

![Cumulative cash](charts/07_cumulative_cash.png)
![Tornado](charts/05_tornado.png)
![Monte Carlo](charts/06_monte_carlo.png)

Break-even points (other assumptions at base): digital adoption **{pct(r.break_even_adoption)}**;
cycle days saved per digital claim **{r.break_even_days:.2f}** (pilot estimate
{-d.per_digital_claim:.2f}).

## 8. Risks

![Risk heatmap](charts/09_risk_heatmap.png)

{risks.to_markdown(r.risks)}

## 9. Recommendation and next steps

1. **Approve** £{r.assumptions["capex"].base / 1e6:.2f}m build plus
   £{r.assumptions["change_cost"].base / 1e3:.0f}k change budget for a national rollout in
   three waves.
2. **Stage-gate at month 6:** continue only if digital adoption is at or above
   {pct(r.break_even_adoption)} and cycle-time savings are at least {r.break_even_days:.1f} days
   per digital claim, measured with the same difference-in-differences method.
3. **Before mobilisation:** close the RACI gaps, complete the DPIA, and agree the
   handler redeployment plan with the contact centre.
4. **Out of scope for phase 1:** AI photo estimating (FNOL-09, Won't), to be revisited when
   photo volumes exceed 20,000.

*Caveats:* the data is synthetic and seeded. Leakage and fraud uplift are judgement-based
ranges, not pilot measurements. Monte Carlo draws assumptions independently, which ignores
correlations such as adoption with cycle-time saving.
"""


def write_all(r: CaseResults, docs: Path) -> list[Path]:
    docs.mkdir(parents=True, exist_ok=True)
    out = write_charts(r, docs / "charts")
    (docs / "BUSINESS_CASE.md").write_text(business_case_md(r), encoding="utf-8")
    (docs / "BACKLOG.md").write_text(
        requirements.to_markdown(r.stories, r.backlog_issues), encoding="utf-8"
    )
    out += requirements.export_features(r.stories, docs / "features")
    return out + [docs / "BUSINESS_CASE.md", docs / "BACKLOG.md"]
