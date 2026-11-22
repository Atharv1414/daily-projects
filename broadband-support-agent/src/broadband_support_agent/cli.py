"""Command line interface: run a conversation, run the eval suite, build the database."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from broadband_support_agent.agent import AgentResult, SupportAgent
from broadband_support_agent.approval import (
    ApprovalPolicy,
    AutoApprove,
    AutoDeny,
    ConsoleApproval,
    ScriptedApproval,
)
from broadband_support_agent.config import Settings
from broadband_support_agent.database import Repository, connect
from broadband_support_agent.datagen import GOLDEN, ensure_database, memory_database
from broadband_support_agent.errors import SupportAgentError
from broadband_support_agent.evals import injection_benchmark, markdown_report, run_suite, summarise
from broadband_support_agent.llm import ClaudeClient
from broadband_support_agent.scenarios import CASES, CASES_BY_ID
from broadband_support_agent.tools import build_registry
from broadband_support_agent.tracing import configure_logging, render_html


def _print_result(result: AgentResult, label: str) -> None:
    print(f"=== {label} ===")
    print(f"Customer: {result.message}")
    for call in result.tool_calls:
        args = json.dumps(call["input"])
        extra = f"  -> {call['error']}" if call.get("error") else ""
        print(f"  [step {call['step']}] {call['tool']}({args}) {call['status'].upper()}{extra}")
    for g in result.state["guardrail_events"]:
        print(f"  [guardrail] {g['kind']}: {g['detail']} (source: {g['source']})")
    if result.problems:
        print(f"  [output guard] {'; '.join(result.problems)}")
        print(f"  [output guard] withheld reply: {result.raw_answer}")
    print(f"Agent: {result.answer}")
    t = result.trace
    est = " (estimated)" if t["estimated_usage"] else ""
    print(
        f"Status: {result.status} · steps {result.steps} · tokens "
        f"{t['input_tokens'] + t['output_tokens']:,}{est} · cost ${t['cost_usd']:.4f} · "
        f"{t['wall_ms']:.1f} ms\n"
    )


def _approval(mode: str, scripted: list[bool] | None = None) -> ApprovalPolicy:
    if scripted is not None:
        return ScriptedApproval(list(scripted))
    return {"auto": AutoApprove(), "deny": AutoDeny()}.get(mode) or ConsoleApproval()


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    sessions = []
    if args.demo:
        ids = (
            [args.scenario]
            if args.scenario
            else [
                "outage_known",
                "line_fault_booked",
                "user_prompt_injection",
                "hallucinated_credit",
            ]
        )
        print("Running in offline demo mode (ScriptedLLM, no API key needed).\n")
        for cid in ids:
            case = CASES_BY_ID.get(cid)
            if case is None:
                print(f"Unknown scenario {cid!r}. Try `support-agent scenarios`.", file=sys.stderr)
                return 2
            from broadband_support_agent.llm import ScriptedLLM

            conn = memory_database(settings.now, n_customers=300, seed=settings.seed)
            agent = SupportAgent(
                ScriptedLLM(case.script),
                build_registry(),
                Repository(conn),
                settings,
                _approval(args.approve, case.approvals),
            )
            result = agent.run(case.message, session_id=f"demo-{cid}")
            _print_result(result, f"{cid} (offline demo mode)")
            sessions.append({"name": cid, **_session(result)})
            conn.close()
    else:
        if not args.message:
            print("Give a customer message, or use --demo.", file=sys.stderr)
            return 2
        db = ensure_database(settings.db_path, settings.now, seed=settings.seed)
        conn = connect(db)
        agent = SupportAgent(
            ClaudeClient(settings.model),
            build_registry(),
            Repository(conn),
            settings,
            _approval(args.approve),
        )
        result = agent.run(args.message)
        _print_result(result, f"live ({settings.model})")
        sessions.append({"name": "live", **_session(result)})
        conn.close()
    if args.trace_html:
        Path(args.trace_html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.trace_html).write_text(render_html(sessions), encoding="utf-8")
        print(f"Trace written to {args.trace_html}")
    return 0


def _session(result: AgentResult) -> dict:
    return {"status": result.status, "trace": result.trace, "spans": result.spans}


def cmd_eval(args: argparse.Namespace, settings: Settings) -> int:
    factory = None
    mode = "offline demo mode (ScriptedLLM)"
    if not args.demo:
        factory = lambda _case: ClaudeClient(settings.model)  # noqa: E731
        mode = f"live ({settings.model})"
    results = run_suite(settings, factory, args.only)
    bench = injection_benchmark()
    summary = summarise(results)
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"{mark}  {r.case_id:<28} {r.category:<12} {r.status:<16} steps={r.steps}")
        for f in r.failures:
            print(f"      - {f}")
    print(
        f"\nPass rate: {summary['passed']}/{summary['cases']} ({summary['pass_rate']:.0%}) "
        f"· by category: {summary['by_category']}"
    )
    print(
        f"Injection detector: blocked {bench['blocked']}/{bench['attacks']} attacks "
        f"({bench['block_rate']:.0%}), false positives {bench['false_positives']}/"
        f"{bench['benign']} ({bench['false_positive_rate']:.0%}); held-out obfuscated attacks "
        f"blocked {bench['hard_blocked']}/{bench['hard_attacks']}"
    )
    out = Path(args.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval_report.md").write_text(
        markdown_report(results, bench, mode, datetime.now()), encoding="utf-8"
    )
    sessions = [{"name": r.case_id, **_session(r.result)} for r in results if r.result]
    (out / "eval_traces.html").write_text(render_html(sessions, "Eval traces"), encoding="utf-8")
    print(f"Reports written to {out}/eval_report.md and {out}/eval_traces.html")
    return 0 if summary["passed"] == summary["cases"] else 1


def cmd_seed(args: argparse.Namespace, settings: Settings) -> int:
    path = ensure_database(settings.db_path, settings.now, seed=settings.seed)
    repo = Repository(connect(path))
    for table in ("customers", "invoices", "outages", "engineer_slots", "help_articles"):
        print(f"{table:<16} {repo.count(table):>7,}")
    print(f"Database ready at {path}")
    return 0


def cmd_scenarios(args: argparse.Namespace, settings: Settings) -> int:
    for case in CASES:
        print(f"{case.id:<28} {case.category:<12} {case.message[:70]}")
    print("\nGolden customers:")
    for g in GOLDEN:
        print(f"  {g.account_id} {g.postcode:<9} {g.situation}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="support-agent", description=__doc__)
    parser.add_argument("--log-level", default="WARNING")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Handle one customer message")
    run.add_argument("message", nargs="?")
    run.add_argument("--demo", action="store_true", help="Offline with ScriptedLLM")
    run.add_argument("--scenario", help="Demo scenario id (see `scenarios`)")
    run.add_argument("--approve", choices=["ask", "auto", "deny"], default="ask")
    run.add_argument("--trace-html", help="Write an HTML trace report here")
    ev = sub.add_parser("eval", help="Run the eval suite")
    ev.add_argument("--demo", action="store_true", help="Offline with ScriptedLLM")
    ev.add_argument("--only", nargs="*", help="Case ids to run")
    ev.add_argument("--report-dir", default="reports")
    sub.add_parser("seed", help="Build the SQLite database")
    sub.add_parser("scenarios", help="List demo/eval scenarios")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    try:
        settings = Settings.from_env()
        handler = {"run": cmd_run, "eval": cmd_eval, "seed": cmd_seed, "scenarios": cmd_scenarios}[
            args.command
        ]
        return handler(args, settings)
    except SupportAgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
