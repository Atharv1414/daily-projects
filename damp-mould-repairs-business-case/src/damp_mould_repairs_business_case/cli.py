"""Command line: export the extract, mine it, simulate options and write the business case."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

from . import datagen, eventlog, mining, pipeline, report
from .model import Parameters
from .simulation import simulate, summarise


def _positive(text: str) -> int:
    value = int(text)
    if value < 2:
        raise argparse.ArgumentTypeError("at least 2 replications are needed for an interval")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="damp-case", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="write the raw event log to CSV")
    extract.add_argument("--out", type=Path, default=Path("data/event_log.csv"))
    mine = sub.add_parser("mine", help="clean and mine an event log")
    mine.add_argument("--log", type=Path, help="CSV; default is the generated extract")
    for name, text in (("report", "write docs/"), ("options", "print the options table")):
        command = sub.add_parser(name, help=text)
        command.add_argument("--replications", type=_positive, default=20)
        command.add_argument("--out", type=Path, default=Path("docs"))
    what_if = sub.add_parser("what-if", help="simulate one staffing choice")
    what_if.add_argument("--surveyors", type=int, default=8)
    what_if.add_argument("--crews", type=int, default=18)
    what_if.add_argument("--admin", type=int, default=1)
    what_if.add_argument("--deadline-queue", action="store_true")
    return parser


def _mine(path: Path | None) -> None:
    raw = (
        datagen.event_log() if path is None else pd.read_csv(path, parse_dates=["started", "ended"])
    )
    log = eventlog.clean(raw)
    for note, count in log.notes:
        print(f"{count:>7,}  {note}")
    conformance = mining.check_conformance(log)
    print(f"\n{log.cases:,} cases, step fitness {conformance.fitness:.1%}, "
          f"fully conforming {conformance.conforming_cases:.1%}")  # fmt: skip
    for violation, count in conformance.violations[:5]:
        print(f"{count:>7,}  {violation}")
    print("\nmost common paths")
    for path_, count, share in mining.variants(log, 4):
        print(f"{count:>7,} {share:>6.1%}  {' > '.join(path_)}")
    print("\nclocks")
    table = mining.compliance(mining.case_records(log), log.events.end_minute.max())
    for row in table.itertuples():
        print(f"{row.met_share:>7.1%}  {row.clock} ({row.breached:,} of {row.cases:,} breached)")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "extract":
            args.out.parent.mkdir(parents=True, exist_ok=True)
            log = datagen.event_log()
            log.to_csv(args.out, index=False)
            print(f"{len(log):,} rows written to {args.out}")
        elif args.command == "mine":
            _mine(args.log)
        elif args.command == "what-if":
            staffing = Parameters(
                surveyors=args.surveyors,
                crews=args.crews,
                admin_officers=args.admin,
                deadline_queue=args.deadline_queue,
            )
            for key, value in summarise(simulate(staffing, seed=1)).items():
                print(f"{key:<20}{value:>12,.3f}")
        else:
            started = time.perf_counter()
            analysis = pipeline.run(args.replications)
            print("\n".join(report.clock_summary(analysis)), "\n")
            print("\n".join(report.options_table(analysis)))
            if args.command == "report":
                for path in report.write_all(analysis, args.out):
                    print(path)
            print(f"{len(analysis.runs) * args.replications} simulated years in "
                  f"{time.perf_counter() - started:.1f}s")  # fmt: skip
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
