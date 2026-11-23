"""Command-line entry point: ``qoe generate | run | report | bench | demo``."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

import pandas as pd

from . import report
from .config import Settings
from .errors import SimulatedCrash
from .generator import generate
from .log import PartitionedLog
from .observability import configure_logging
from .pipeline import StreamProcessor
from .sink import DuckDBSink


def _log(s: Settings) -> PartitionedLog:
    return PartitionedLog(s.log_dir, s.partitions, s.segment_size)


def cmd_generate(s: Settings, args: argparse.Namespace) -> None:
    if s.log_dir.exists():
        shutil.rmtree(s.log_dir)
    summary = generate(_log(s), sessions=args.sessions, seed=args.seed)
    print(
        f"sessions={summary.sessions:,} events={summary.events:,} log_records={summary.records:,}"
    )
    for key, value in sorted(summary.counts.items()):
        print(f"  {key:<28} {value:>8,}")


def cmd_run(s: Settings, args: argparse.Namespace) -> None:
    sink = DuckDBSink(s.warehouse_path)
    try:
        processor = StreamProcessor(s, _log(s), sink, crash_after_polls=args.crash_after_polls)
        result = processor.run(drain=not args.no_drain, max_polls=args.max_polls)
        stats = {k: v for k, v in result.stats.items() if k != "delay_histogram"}
        print(
            json.dumps(
                {"polls": result.polls, "checkpoints": result.checkpoints, **stats}, indent=2
            )
        )
    except SimulatedCrash as exc:
        print(f"CRASH: {exc}. Committed state is intact; re-run `qoe run` to resume.")
    finally:
        sink.close()


def cmd_report(s: Settings, args: argparse.Namespace) -> None:
    sink = DuckDBSink(s.warehouse_path)
    try:
        pd.set_option("display.width", 140)
        pd.set_option("display.max_columns", 20)
        for name, frame in report.tables(sink).items():
            print(f"\n== {name}")
            print(frame.to_string(index=False))
        out = Path(args.charts)
        runs = sink.query("SELECT stats FROM pipeline_runs ORDER BY started_at")
        delays: dict[str, int] = {}
        for raw in runs["stats"]:
            for k, v in json.loads(raw).get("delay_histogram", {}).items():
                delays[k] = delays.get(k, 0) + v
        paths = [
            report.chart_rebuffer_by_cdn(sink, out),
            report.chart_concurrency(sink, out),
            report.chart_vst_by_device(sink, out),
            report.chart_delay_profile(delays, s.allowed_lateness_ms / 1000, out),
        ]
        print("\ncharts: " + ", ".join(str(p) for p in paths))
    finally:
        sink.close()


def cmd_bench(s: Settings, args: argparse.Namespace) -> None:
    rows = []
    for every in args.intervals:
        with tempfile.TemporaryDirectory() as tmp:
            sink = DuckDBSink(Path(tmp) / "bench.duckdb")
            run = StreamProcessor(replace(s, checkpoint_every_polls=every), _log(s), sink).run()
            sink.close()
        st = run.stats
        rows.append(
            {
                "checkpoint_every": every,
                "checkpoints": st["checkpoints"],
                "records_per_s": st["records_per_s"],
                "avg_checkpoint_ms": st["avg_checkpoint_ms"],
                "max_checkpoint_kb": st["max_checkpoint_kb"],
                "elapsed_s": st["elapsed_s"],
            }
        )
        print(json.dumps(rows[-1]))
    if args.charts:
        print(report.chart_benchmark(rows, Path(args.charts)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qoe", description=__doc__)
    parser.add_argument("--log-level", default="WARNING")
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate", help="write synthetic telemetry to the partitioned log")
    g.add_argument("--sessions", type=int, default=12_000)
    g.add_argument("--seed", type=int, default=7)
    r = sub.add_parser("run", help="process the log into the DuckDB warehouse")
    r.add_argument("--crash-after-polls", type=int, default=None)
    r.add_argument("--max-polls", type=int, default=None)
    r.add_argument("--no-drain", action="store_true", help="leave open windows open at the end")
    rep = sub.add_parser("report", help="print analytics and write charts")
    rep.add_argument("--charts", default="docs/charts")
    b = sub.add_parser("bench", help="throughput vs checkpoint interval")
    b.add_argument("--intervals", type=int, nargs="+", default=[1, 5, 20])
    b.add_argument("--charts", default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    settings = Settings.from_env()
    {"generate": cmd_generate, "run": cmd_run, "report": cmd_report, "bench": cmd_bench}[
        args.command
    ](settings, args)


if __name__ == "__main__":
    main()
