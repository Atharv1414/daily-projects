"""Command line: seed, serve, demo, ask, evals."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

import anyio

from .agent.approval import AutoApprover, ConsoleApprover, DenyAll
from .agent.guardrails import ToolPolicy
from .agent.llm import ClaudeClient, LLMError, ScriptedLLM
from .agent.loop import AgentResult, PlanningAgent, pretty
from .agent.mcp_bridge import stdio_gateway
from .agent.scenarios import TRIAGE_TASK, triage_steps
from .config import Settings
from .datagen import build_store
from .evals import run_all, to_json


def _report(result: AgentResult, trace_dir: Path, name: str) -> None:
    t = result.tracer.totals()
    print("\nTrajectory:")
    print(pretty(result))
    print("\nAnswer:\n" + result.answer)
    est = " (estimated, scripted model)" if t["tokens_estimated"] else ""
    print(
        f"\nstop={result.stop} steps={result.steps} model_calls={t['model_calls']} "
        f"tool_calls={t['tool_calls']} tool_errors={t['tool_errors']} "
        f"guardrail_events={t['guardrail_events']} approvals={t['approvals']}"
    )
    print(
        f"tokens in/out={t['input_tokens']}/{t['output_tokens']}{est} "
        f"cost=${t['cost_usd']:.4f}{est} model_ms={t['model_latency_ms']} "
        f"tool_ms={t['tool_latency_ms']}"
    )
    check = result.answer_check
    print(f"answer check: {'grounded' if check.ok else check}")
    trace_dir.mkdir(parents=True, exist_ok=True)
    result.tracer.to_jsonl(trace_dir / f"{name}.jsonl")
    result.tracer.to_html(trace_dir / f"{name}.html", f"Agent trace: {name}", result.answer)
    print(f"trace: {trace_dir / (name + '.html')}")


async def _run(task: str, llm, approver, settings: Settings, policy: ToolPolicy, db: str):
    async with stdio_gateway({"PLANNING_DB": db}) as gateway:
        agent = PlanningAgent(llm, gateway, approver, settings, policy)
        return await agent.run(task)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planning-mcp")
    sub = parser.add_subparsers(dest="cmd", required=True)
    seed = sub.add_parser("seed", help="create the casework database")
    seed.add_argument("--size", type=int, default=None)
    sub.add_parser("serve", help="run the MCP server over stdio")
    demo = sub.add_parser("demo", help="offline demo with the scripted model, over stdio")
    demo.add_argument("--trace-dir", default="reports")
    ask = sub.add_parser("ask", help="ask the live agent (needs ANTHROPIC_API_KEY)")
    ask.add_argument("task")
    ask.add_argument("--officer", default="Duty planning officer")
    ask.add_argument("--read-only", action="store_true", help="hide the write tools")
    ask.add_argument("--no-writes", action="store_true", help="decline every write")
    ask.add_argument("--trace-dir", default="reports")
    ev = sub.add_parser("evals", help="run the evaluation suite")
    ev.add_argument("--live", action="store_true", help="run agent scenarios against Claude")
    ev.add_argument("--json", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    settings = Settings.from_env()

    if args.cmd == "seed":
        store = build_store(settings.db_path, n=args.size or settings.seed_size)
        print(json.dumps(store.counts()))
        return 0
    if args.cmd == "serve":
        from .server import main as serve

        serve()
        return 0
    if args.cmd == "demo":
        print("offline demo mode: ScriptedLLM plays the model; the MCP server is real\n")
        print("Task: " + TRIAGE_TASK)
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "demo.db")
            build_store(db, n=settings.seed_size).close()
            result = anyio.run(
                _run, TRIAGE_TASK, ScriptedLLM(triage_steps()),
                AutoApprover("C. Mistry (demo auto-approval)"), settings, ToolPolicy(), db,
            )  # fmt: skip
        _report(result, Path(args.trace_dir), "demo-trace")
        return 0 if result.stop == "answered" else 1
    if args.cmd == "ask":
        try:
            llm = ClaudeClient(settings.model, settings.max_tokens_per_call)
        except LLMError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        build_store(settings.db_path, n=settings.seed_size).close()
        approver = DenyAll() if args.no_writes else ConsoleApprover(args.officer)
        policy = ToolPolicy.read_only() if args.read_only else ToolPolicy()
        result = anyio.run(_run, args.task, llm, approver, settings, policy, settings.db_path)
        _report(result, Path(args.trace_dir), "live-trace")
        return 0 if result.stop == "answered" else 1
    if args.cmd == "evals":
        factory = None
        if args.live:
            ClaudeClient(settings.model)  # fail fast without a key

            def factory():
                return ClaudeClient(settings.model, settings.max_tokens_per_call)

        report = anyio.run(run_all, factory)
        print(report.render())
        if args.json:
            Path(args.json).write_text(to_json(report), encoding="utf-8")
        return 0 if report.rate() == 1.0 else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
