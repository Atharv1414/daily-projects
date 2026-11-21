"""Command-line interface: ``hotel-agent init-db | ask | eval | tools | trace-html``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from hotel_revenue_agent.agent import AgentResult, AnalystAgent
from hotel_revenue_agent.approval import AutoApprove, ConsoleApproval
from hotel_revenue_agent.config import Settings
from hotel_revenue_agent.database import Warehouse
from hotel_revenue_agent.datagen import ensure_database, generate
from hotel_revenue_agent.errors import AgentError
from hotel_revenue_agent.evals import ALL_CASES, format_report, run_suite
from hotel_revenue_agent.llm import ClaudeClient, LLMClient, ScriptedLLM
from hotel_revenue_agent.tools import ToolRegistry, build_tools
from hotel_revenue_agent.tracing import Tracer, configure_logging, load_spans, render_html

DEFAULT_SCENARIO = "top_revpar_2025"


def _find_scenario(question: str | None, scenario: str | None):
    by_id = {c.id: c for c in ALL_CASES}
    if scenario:
        if scenario not in by_id:
            raise AgentError(f"Unknown scenario {scenario!r}. Try: {', '.join(by_id)}")
        return by_id[scenario]
    if question:
        for case in ALL_CASES:
            if case.question.lower().strip(" ?") == question.lower().strip(" ?"):
                return case
    return by_id[DEFAULT_SCENARIO]


def _print_result(result: AgentResult) -> None:
    print(f"\nQ: {result.question}")
    for call in result.tool_calls:
        arg = (
            call["input"].get("sql")
            or call["input"].get("table")
            or call["input"].get("metric")
            or ""
        )
        arg = " ".join(str(arg).split())
        print(f"  step {call['step']}: {call['tool']:<13} [{call['status']}] {arg[:90]}")
        if call.get("error"):
            print(f"           -> {call['error']}")
    print(f"\nA: {result.answer}")
    t = result.trace
    print(
        f"\n[{result.status}] {result.steps} steps · {t['llm_calls']} LLM calls · "
        f"{t['tool_calls']} tool calls ({t['tool_errors']} errors) · "
        f"{t['input_tokens'] + t['output_tokens']} tokens · ${t['cost_usd']:.4f} · "
        f"LLM {t['llm_ms']} ms / tools {t['tool_ms']} ms"
    )


def cmd_ask(args: argparse.Namespace, settings: Settings) -> int:
    ensure_database(settings.db_path)
    llm: LLMClient
    question = args.question
    if args.demo:
        case = _find_scenario(question, args.scenario)
        question = case.question
        assert case.reference is not None
        llm = ScriptedLLM(case.reference("reference"))
        approval = case.approval()
        print("(offline demo mode: scripted model, real tools and database)")
    else:
        if not question:
            raise AgentError("A question is required in live mode.")
        llm = ClaudeClient(settings.model, settings.max_tokens_per_call)
        approval = AutoApprove() if args.yes else ConsoleApproval()
    warehouse = Warehouse(settings.db_path, settings.max_rows, settings.query_timeout_ms)
    try:
        registry = ToolRegistry(build_tools(warehouse, settings.reports_dir))
        tracer = Tracer(settings.price(llm.model))
        result = AnalystAgent(llm, registry, settings, approval, tracer).run(question)
    finally:
        warehouse.close()
    _print_result(result)
    path = tracer.write_jsonl(settings.traces_dir)
    print(f"trace: {os.path.relpath(path)}")
    return 0 if result.ok else 2


def cmd_eval(args: argparse.Namespace, settings: Settings) -> int:
    ensure_database(settings.db_path)
    reports_dir = settings.traces_dir / "eval-reports"
    s = replace(settings, reports_dir=reports_dir)
    if args.live:
        factory = lambda case: ClaudeClient(settings.model, settings.max_tokens_per_call)  # noqa: E731
        reports = [run_suite(s, "live:" + settings.model, llm_factory=factory)]
    else:
        print("(offline demo mode: scripted trajectories, real tools and database)")
        reports = [run_suite(s, "reference")]
        if args.compare_naive:
            reports.append(run_suite(s, "naive"))
    print(format_report(*reports))
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                [
                    {
                        "variant": r.variant,
                        "pass_rate": r.pass_rate,
                        "cases": [
                            {
                                "id": c.case.id,
                                "passed": c.passed,
                                "status": c.result.status,
                                "checks": [vars(k) for k in c.checks],
                            }
                            for c in r.results
                        ],
                    }
                    for r in reports
                ],
                indent=2,
            )
        )
    return 0 if reports[0].pass_rate == 1.0 else 1


def cmd_tools(args: argparse.Namespace, settings: Settings) -> int:
    ensure_database(settings.db_path)
    warehouse = Warehouse(settings.db_path)
    try:
        for spec in ToolRegistry(build_tools(warehouse, settings.reports_dir)).specs():
            print(json.dumps(spec, indent=2))
    finally:
        warehouse.close()
    return 0


def cmd_init_db(args: argparse.Namespace, settings: Settings) -> int:
    summary = generate(settings.db_path, bookings=args.bookings, seed=args.seed)
    print(f"Created {settings.db_path.name}: {summary}")
    return 0


def cmd_trace_html(args: argparse.Namespace, settings: Settings) -> int:
    trace = (
        Path(args.trace)
        if args.trace
        else max(settings.traces_dir.glob("run-*.jsonl"), key=lambda p: p.stat().st_mtime)
    )
    out = Path(args.out)
    out.write_text(render_html(load_spans(trace), f"Trace {trace.stem}"), encoding="utf-8")
    print(f"wrote {out}")
    return 0


def cmd_bench(args: argparse.Namespace, settings: Settings) -> int:
    from hotel_revenue_agent import bench

    ensure_database(settings.db_path)
    for key, value in bench.run(settings).items():
        print(f"{key:<20} {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hotel-agent", description=__doc__)
    p.add_argument("--log-level", default="WARNING")
    p.add_argument("--json-logs", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="ask the analyst agent a question")
    ask.add_argument("question", nargs="?")
    ask.add_argument("--demo", action="store_true", help="offline scripted model, no API key")
    ask.add_argument("--scenario", help="demo scenario id (see `eval` case ids)")
    ask.add_argument("--yes", action="store_true", help="auto-approve side-effecting tools")
    ask.set_defaults(func=cmd_ask)

    ev = sub.add_parser("eval", help="run the evaluation suite")
    ev.add_argument("--live", action="store_true", help="evaluate the real model")
    ev.add_argument(
        "--compare-naive",
        action="store_true",
        help="also run the no-glossary variant and report regressions",
    )
    ev.add_argument("--json", help="write machine-readable results here")
    ev.set_defaults(func=cmd_eval)

    db = sub.add_parser("init-db", help="(re)generate the synthetic hotel database")
    db.add_argument("--bookings", type=int, default=200_000)
    db.add_argument("--seed", type=int, default=42)
    db.set_defaults(func=cmd_init_db)

    sub.add_parser("tools", help="print the tool schemas sent to the model").set_defaults(
        func=cmd_tools
    )

    sub.add_parser("bench", help="guardrail and query latency benchmark").set_defaults(
        func=cmd_bench
    )

    th = sub.add_parser("trace-html", help="render a JSONL trace as HTML")
    th.add_argument("--trace")
    th.add_argument("--out", default="trace.html")
    th.set_defaults(func=cmd_trace_html)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level, args.json_logs)
    settings = Settings.from_env()
    try:
        return args.func(args, settings)
    except AgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
