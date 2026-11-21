from dataclasses import replace

import pytest

from hotel_revenue_agent.agent import AnalystAgent
from hotel_revenue_agent.approval import AutoApprove, AutoDeny, ConsoleApproval
from hotel_revenue_agent.llm import LLMResponse, ScriptedLLM, ToolCall, Turn


def make(registry, settings, turns, **kw):
    return AnalystAgent(ScriptedLLM(turns), registry, settings, **kw)


def test_happy_path_uses_real_query_result(registry, settings):
    turns = [
        Turn(calls=[ToolCall("run_sql", {"sql": "SELECT COUNT(*) FROM hotels"})]),
        Turn(final=lambda p: f"There are {p['rows'][0][0]} hotels."),
    ]
    result = make(registry, settings, turns).run("How many hotels?")
    assert result.ok and result.answer == "There are 12 hotels."
    assert result.steps == 2 and result.trace["tool_calls"] == 1


def test_self_corrects_after_sql_error(registry, settings):
    turns = [
        Turn(calls=[ToolCall("run_sql", {"sql": "SELECT nope FROM hotels"})]),
        Turn(calls=[ToolCall("run_sql", {"sql": "SELECT COUNT(*) FROM hotels"})]),
        Turn(final=lambda p: str(p["rows"][0][0])),
    ]
    result = make(registry, settings, turns).run("count")
    assert result.ok and result.answer == "12"
    assert [c["status"] for c in result.tool_calls] == ["error", "ok"]


def test_error_message_and_hint_reach_the_model(registry, settings):
    seen = {}

    class Spy(ScriptedLLM):
        def complete(self, system, messages, tools):
            if len(messages) > 1:
                seen["content"] = messages[-1]["content"][0]
            return super().complete(system, messages, tools)

    turns = [
        Turn(calls=[ToolCall("run_sql", {"sql": "SELECT nope FROM hotels"})]),
        Turn(final="done"),
    ]
    AnalystAgent(Spy(turns), registry, settings).run("q")
    assert seen["content"]["is_error"] is True
    assert "HINT" in seen["content"]["content"]


def test_parallel_tool_calls_return_in_one_message(registry, settings):
    captured = []

    class Spy(ScriptedLLM):
        def complete(self, system, messages, tools):
            captured.append(list(messages))
            return super().complete(system, messages, tools)

    turns = [
        Turn(calls=[ToolCall("list_tables", {}), ToolCall("describe_table", {"table": "hotels"})]),
        Turn(final="ok"),
    ]
    AnalystAgent(Spy(turns), registry, settings).run("q")
    last_user = captured[-1][-1]
    assert last_user["role"] == "user" and len(last_user["content"]) == 2


def test_step_budget_stops_runaway_agent(registry, settings):
    turns = [Turn(calls=[ToolCall("list_tables", {})])] * 10
    result = make(registry, replace(settings, max_steps=3), turns).run("loop")
    assert result.status == "budget_exceeded" and result.steps == 3


def test_consecutive_errors_stop_the_loop(registry, settings):
    turns = [Turn(calls=[ToolCall("run_sql", {"sql": "DROP TABLE hotels"})])] * 5
    result = make(registry, settings, turns).run("break it")
    assert result.status == "budget_exceeded"
    assert result.guardrail_blocks == settings.max_consecutive_errors


def test_token_budget(registry, settings):
    turns = [Turn(calls=[ToolCall("list_tables", {})])] * 5
    result = make(registry, replace(settings, max_total_tokens=1_000), turns).run("q")
    assert result.status == "budget_exceeded" and "Token budget" in result.answer


def test_side_effect_denied_by_default(registry, settings):
    turns = [
        Turn(
            calls=[ToolCall("save_report", {"title": "Report", "markdown": "Some markdown body"})]
        ),
        Turn(final="ok"),
    ]
    policy = AutoDeny()
    result = make(registry, settings, turns, approval=policy).run("save")
    assert policy.asked == ["save_report"] and result.approvals_denied == 1
    assert not settings.reports_dir.exists() or not list(settings.reports_dir.iterdir())


@pytest.mark.parametrize("answer,saved", [("y", True), ("n", False), ("", False)])
def test_console_approval(registry, settings, answer, saved):
    turns = [
        Turn(
            calls=[ToolCall("save_report", {"title": "Report", "markdown": "Some markdown body"})]
        ),
        Turn(final="ok"),
    ]
    policy = ConsoleApproval(ask=lambda _: answer, echo=lambda _: None)
    make(registry, settings, turns, approval=policy).run("save")
    files = list(settings.reports_dir.glob("*.md")) if settings.reports_dir.exists() else []
    assert bool(files) is saved


def test_auto_approve_runs_side_effect(registry, settings):
    turns = [
        Turn(
            calls=[ToolCall("save_report", {"title": "Report", "markdown": "Some markdown body"})]
        ),
        Turn(final="ok"),
    ]
    make(registry, settings, turns, approval=AutoApprove()).run("save")
    assert len(list(settings.reports_dir.glob("*.md"))) == 1


def test_truncated_model_output_is_an_error(registry, settings):
    class Truncating:
        model = "scripted"

        def complete(self, system, messages, tools):
            return LLMResponse([{"type": "text", "text": "partial"}], "max_tokens")

    result = AnalystAgent(Truncating(), registry, settings).run("q")
    assert result.status == "error" and "truncated" in result.answer


def test_script_exhaustion_is_reported_not_raised(registry, settings):
    result = make(registry, settings, [Turn(calls=[ToolCall("list_tables", {})])]).run("q")
    assert result.status == "error"


def test_empty_question_rejected(registry, settings):
    with pytest.raises(ValueError):
        make(registry, settings, []).run("   ")


def test_tracer_records_cost_and_latency(registry, settings):
    agent = make(registry, settings, [Turn(calls=[ToolCall("list_tables", {})]), Turn(final="ok")])
    agent.run("q")
    kinds = [s.kind for s in agent.tracer.spans]
    assert kinds == ["llm", "tool", "llm"]
    assert agent.tracer.summary()["cost_usd"] > 0
    path = agent.tracer.write_jsonl(settings.traces_dir)
    assert len(path.read_text().splitlines()) == 3
