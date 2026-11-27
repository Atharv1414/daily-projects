"""Command line: run the experiment, build the report, triage a message, or look at the data."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from pathlib import Path

from .config import ROOT, ExperimentConfig, quick
from .data import SPLIT_SIZES, generate, write_jsonl

ARTIFACTS = ROOT / "artifacts"
REPORTS = ROOT / "reports"


def _has_torch() -> bool:
    return importlib.util.find_spec("torch") is not None


def cmd_data(args: argparse.Namespace) -> int:
    messages = generate(args.seed)
    write_jsonl(messages, Path(args.out))
    sample = [m for m in messages if m.id.endswith(("00000", "00001", "00002"))]
    for m in sample:
        print(f"[{m.split}] {m.triage.to_text():<55} {m.text}")
    print(f"Wrote {len(messages):,} messages to {args.out}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .experiment import run
    from .report import build

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    with_torch = _has_torch() and not args.baselines_only
    if not with_torch and not args.baselines_only:
        print(
            "torch is not installed: running the baselines only. "
            "pip install -e '.[torch]' for the transformer.",
            file=sys.stderr,
        )
    cfg = quick() if args.quick else ExperimentConfig()
    sizes = (
        {"train": 600, "val": 150, "test_seen": 150, "test_unseen": 150, "unlabelled": 300}
        if args.quick
        else SPLIT_SIZES
    )
    out = Path(args.out)
    metrics = run(cfg, out, sizes, with_torch=with_torch)
    if not args.quick:
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        build(REPORTS / "metrics.json", REPORTS)
        if (out / "lora_adapter.npz").exists():
            (REPORTS / "lora_adapter.npz").write_bytes((out / "lora_adapter.npz").read_bytes())
    print(f"Done in {metrics['wall_seconds']} s")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report import build, table

    for path in build(Path(args.metrics), Path(args.out)):
        print(f"wrote {path}")
    print(table(json.loads(Path(args.metrics).read_text(encoding="utf-8"))))
    return 0


def cmd_triage(args: argparse.Namespace) -> int:
    """Triage messages with the TF-IDF model, which needs no torch, using the abstention threshold
    the experiment chose on validation data (or --threshold)."""
    from .baselines import TfidfLogistic
    from .data import by_split

    threshold = args.threshold
    metrics_path = REPORTS / "metrics.json"
    if threshold is None and metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        threshold = metrics["baselines"]["TF-IDF + logistic regression"]["abstention"]["threshold"]
    threshold = 0.8 if threshold is None else threshold
    train = by_split(generate(args.seed))["train"]
    model = TfidfLogistic().fit(train)
    for text, triage, conf in zip(
        args.text, model.predict(args.text), model.confidence(args.text), strict=True
    ):
        verdict = "answer" if conf >= threshold else "send to a person"
        print(f"{triage.to_text():<55} confidence {conf:.2f} -> {verdict}\n    {text}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="energy-triage", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("data", help="generate the synthetic messages as JSONL")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", default=str(ROOT / "data" / "messages.jsonl"))
    p.set_defaults(fn=cmd_data)

    p = sub.add_parser("run", help="run the whole experiment and rebuild the report")
    p.add_argument("--quick", action="store_true", help="tiny model and data, for a smoke test")
    p.add_argument("--baselines-only", action="store_true")
    p.add_argument("--out", default=str(ARTIFACTS))
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("report", help="rebuild charts and table from a metrics file")
    p.add_argument("--metrics", default=str(REPORTS / "metrics.json"))
    p.add_argument("--out", default=str(REPORTS))
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser(
        "triage", help="triage messages with the TF-IDF baseline and its abstention threshold"
    )
    p.add_argument("text", nargs="+")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--threshold", type=float, default=None)
    p.set_defaults(fn=cmd_triage)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
