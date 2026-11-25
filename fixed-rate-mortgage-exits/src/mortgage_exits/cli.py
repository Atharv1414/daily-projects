"""Command line: `mortgage-exits generate` writes the raw tables, `mortgage-exits run` the study."""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from pathlib import Path

import pandas as pd

from mortgage_exits import datagen, report
from mortgage_exits.config import Economics, Study

log = logging.getLogger("mortgage_exits")


def load(folder: Path) -> datagen.RawData:
    """Reads tables written by `generate`. Text stays text, so cleaning sees the real mess."""
    missing = [n for n in ("accounts", "events", "rates") if not (folder / f"{n}.csv").exists()]
    if missing:
        raise FileNotFoundError(f"{folder} has no {', '.join(missing)}. Run `generate` first.")
    return datagen.RawData(
        pd.read_csv(folder / "accounts.csv", dtype={"ltv": "string"}),
        pd.read_csv(folder / "events.csv"),
        pd.read_csv(folder / "rates.csv"),
    )


def generate(study: Study, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    raw = datagen.generate(study)
    for name in ("accounts", "events", "rates"):
        getattr(raw, name).to_csv(folder / f"{name}.csv", index=False)
        log.info("wrote %s.csv (%d rows)", name, len(getattr(raw, name)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mortgage-exits", description=__doc__)
    parser.add_argument("command", choices=["generate", "run"])
    parser.add_argument(
        "--data", type=Path, help="folder of CSVs; without it the data is simulated"
    )
    parser.add_argument("--out", type=Path, default=Path("output"))
    parser.add_argument("--accounts", type=int)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    study = Study.from_env()
    changes = {
        k: v for k, v in {"accounts": args.accounts, "seed": args.seed}.items() if v is not None
    }
    try:
        study = replace(study, **changes)
        if args.command == "generate":
            generate(study, args.data or Path("data"))
            return 0
        raw = load(args.data) if args.data else datagen.generate(study)
        economics = Economics()
        results = report.analyse(raw, study, economics)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        log.error("%s", error)
        return 1
    path = report.write(results, study, economics, args.out)
    s = report.summary(results, study)
    print(f"{s['mortgages']:,} mortgages, {s['person_months']:,} person-months")
    print(
        f"Left for another lender within {study.max_month} months: {s['left']:.1%} "
        f"({s['left_low']:.1%} to {s['left_high']:.1%}); "
        f"ignoring competing risks: {s['left_naive']:.1%}"
    )
    print(f"Gone before the fix ends: {s['left_before_fix_ends'] / s['left']:.0%} of leavers")
    print("Brier score on later mortgages (lower is better):")
    for name, v in s["brier"].items():
        print(f"  {name:<34}{v:.4f}")
    print(
        f"AUC {s['auc']:.3f}. Calling a fifth, by chance x balance, reaches "
        f"{s['reached_at_20']['Chance x balance']:.0%} of lost margin."
    )
    print(f"Report: {path}")
    return 0
