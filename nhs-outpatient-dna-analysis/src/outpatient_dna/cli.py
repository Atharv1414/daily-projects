"""``dna-analysis`` command line: generate the extract and run the full analysis."""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

from outpatient_dna import report
from outpatient_dna.analysis import headline, run
from outpatient_dna.config import Paths
from outpatient_dna.datagen import ensure_data, generate


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dna-analysis", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate", help="write the synthetic PAS extract to data/")
    g.add_argument("--patients", type=int, default=60_000)
    g.add_argument("--appointments", type=int, default=260_000)
    g.add_argument("--seed", type=int, default=2024)
    r = sub.add_parser("run", help="clean, analyse, chart and write FINDINGS.md")
    r.add_argument("--no-figures", action="store_true")
    args = p.parse_args(argv)
    paths = Paths.from_env()

    if args.command == "generate":
        s = generate(paths.data_dir, args.patients, args.appointments, args.seed)
        print(
            f"wrote {s.appointments:,} appointments, {s.patients:,} patients, "
            f"{s.trial_rows:,} trial allocations to {paths.data_dir.name}/"
        )
        return 0

    ensure_data(paths.data_dir)
    t0 = time.perf_counter()
    results = run(paths, make_figures=not args.no_figures)
    path = report.write(results, paths.reports_dir)
    h = headline(results)
    print(
        f"DNA rate {h['dna_rate']:.2%} | 2025 DNAs {h['dnas_2025']:,.0f} (£{h['cost_2025']:,.0f})"
    )
    print(
        f"SMS trial: {h['trial_control']:.2%} -> {h['trial_treatment']:.2%} "
        f"(RRR {h['trial_rrr']:.1%}, p={h['trial_p']:.1e}, NNT {h['trial_nnt']:.0f})"
    )
    print(
        f"Risk model: test AUC {h['auc_test']:.3f}, top decile holds "
        f"{h['top_decile_capture']:.1%} of DNAs"
    )
    print(
        f"Forecast: best={h['best_forecast']} MAE {h['best_mae']:.1f}/wk "
        f"({h['mae_vs_naive']:.1%} better than naive)"
    )
    print(
        f"SMS rollout saving £{h['sms_saving']:,.0f}/yr; targeted calls net "
        f"£{h['calls_net']:,.0f}/yr"
    )
    print(
        f"{len(results.figures)} figures, findings at {path.name} ({time.perf_counter() - t0:.1f}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
