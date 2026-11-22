"""fnol-case: run the analysis, the financial model and generate the business case pack."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from fnol_business_case import finance, report
from fnol_business_case.datagen import GenConfig, generate_claims, save


def _summary(r: report.CaseResults) -> None:
    b, d, m, mc = r.baseline, r.did, r.metrics, r.monte_carlo
    print("Baseline (12 months pre-pilot)")
    print(
        f"  claims {b['annual_claims']:,.0f} · phone share {b['phone_share']:.1%} · "
        f"mean days to settle {b['mean_days_to_settle']:.1f} · hire cost "
        f"{report.gbp(b['total_rental_cost'])} · NPS {b['nps']:.0f}"
    )
    print("Pilot evaluation")
    print(
        f"  DiD days to settle {d.estimate:+.2f} (95% CI {d.ci_low:+.2f} to {d.ci_high:+.2f}) · "
        f"take-up {d.digital_share_post:.1%} · per digital claim {d.per_digital_claim:+.2f} "
        f"days · pre-trend slope {d.pre_trend_slope:+.3f} (p={d.pre_trend_p:.2f})"
    )
    for c in r.comparisons:
        print(
            f"  {c.metric:<24} digital {c.digital_mean:6.2f} vs phone {c.phone_mean:6.2f} "
            f"(Δ {c.difference:+.2f}, 95% CI {c.ci_low:+.2f} to {c.ci_high:+.2f}, "
            f"d={c.cohens_d:+.2f})"
        )
    print(
        f"  hire days per extra cycle day: {r.rental.slope_rental_days_per_cycle_day:.2f} "
        f"(R²={r.rental.r_squared:.2f})"
    )
    print("Financial case (5 years, 8% discount rate)")
    print(
        f"  NPV {report.gbp(m.npv)} · IRR {m.irr:.1%} · payback {m.payback:.1f} yrs "
        f"(discounted {m.discounted_payback:.1f}) · ROI {m.roi:.0%}"
    )
    print(
        f"  Monte Carlo ({len(mc.npvs):,} runs): P(NPV>0) {mc.p_positive:.1%} · "
        f"P10 {report.gbp(mc.p10)} · P50 {report.gbp(mc.p50)} · P90 {report.gbp(mc.p90)}"
    )
    print(
        f"  break-even adoption {r.break_even_adoption:.1%} · break-even days saved "
        f"{r.break_even_days:.2f}"
    )
    print(
        "  top sensitivities: "
        + "; ".join(
            f"{row.assumption} ({report.gbp(row.npv_low)} to {report.gbp(row.npv_high)})"
            for row in r.tornado.head(3).itertuples()
        )
    )
    cur, fut = r.process_metrics["current"], r.process_metrics["future"]
    print(
        f"Process: lead time {cur.lead_time_hours:.0f}h -> {fut.lead_time_hours:.0f}h · PCE "
        f"{cur.process_cycle_efficiency:.1%} -> {fut.process_cycle_efficiency:.1%} · handoffs "
        f"{cur.handoffs:.0f} -> {fut.handoffs:.1f}"
    )
    gaps = [f for f in r.raci_findings if f.severity != "error"]
    print(
        f"Backlog: {len(r.stories)} stories, {len(r.backlog_issues)} validation notes · RACI: "
        f"{len(gaps)} gaps · Risks: {len(r.risks)}"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fnol-case", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="Run everything and write docs/ (business case pack)")
    rep.add_argument("--docs", default="docs")
    sub.add_parser("summary", help="Print the key numbers only")
    g = sub.add_parser("generate", help="Write the seeded claims CSV")
    g.add_argument("--out", default="data/generated")
    sens = sub.add_parser("what-if", help="Re-run the model with assumption overrides")
    sens.add_argument("overrides", nargs="+", help="name=value, e.g. target_adoption=0.4")
    args = p.parse_args(argv)

    if args.command == "generate":
        path = save(generate_claims(GenConfig()), Path(args.out))
        print(f"wrote {path}")
        return 0
    t0 = time.perf_counter()
    r = report.run()
    if args.command == "what-if":
        v = finance.values(r.assumptions)
        for item in args.overrides:
            name, _, value = item.partition("=")
            if name not in v:
                print(f"unknown assumption {name!r}; choose from {sorted(v)}", file=sys.stderr)
                return 2
            v[name] = float(value)
        base, new = r.metrics, finance.evaluate(v)
        print(
            f"NPV {report.gbp(base.npv)} -> {report.gbp(new.npv)} · IRR {base.irr:.1%} -> "
            f"{report.pct(new.irr)} · payback {report.years(base.payback)} -> "
            f"{report.years(new.payback)}"
        )
        return 0
    _summary(r)
    if args.command == "report":
        paths = report.write_all(r, Path(args.docs))
        print(f"Wrote {len(paths)} files to {args.docs}/ in {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
