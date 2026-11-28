"""The agent loop with the scripted model: budgets, allowlist, approvals, guardrails."""

import pytest

from planning_casework_mcp.agent.approval import ConsoleApprover, ScriptedApprover
from planning_casework_mcp.agent.guardrails import (
    check_answer,
    dates_in,
    to_model_schema,
    validate_args,
)
from planning_casework_mcp.agent.llm import ClaudeClient, LLMError, ScriptedLLM, ScriptStep
from planning_casework_mcp.agent.loop import PlanningAgent
from planning_casework_mcp.agent.scenarios import TRIAGE_TASK, triage_steps
from planning_casework_mcp.config import Settings
from planning_casework_mcp.evals import run_all

pytestmark = pytest.mark.anyio


def test_model_schema_hides_approver():
    schema = {"properties": {"ref": {"type": "string"}, "approved_by": {"type": "string"}},
              "required": ["ref", "approved_by"]}  # fmt: skip
    out = to_model_schema(schema)
    assert "approved_by" not in out["properties"] and out["required"] == ["ref"]


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ({}, "missing required argument 'ref'"),
        ({"ref": 5}, "wrong type"),
        ({"ref": "x", "extra": 1}, "unknown argument"),
        ({"ref": "x", "limit": True}, "wrong type"),  # bools are not integers
        ({"ref": "x" * 3000}, "too long"),
    ],
)
def test_validate_args(args, error):
    schema = {"properties": {"ref": {"type": "string"},
                             "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}]}},
              "required": ["ref"]}  # fmt: skip
    assert any(error in e for e in validate_args(schema, args))


def test_answer_grounding():
    assert dates_in("due 19 November 2026 or 2026-11-19") == {
        __import__("datetime").date(2026, 11, 19)
    }
    check = check_answer("Due 2026-11-19; the draft has been saved.", ['{"d":"2026-11-19"}'], set())
    assert check.ungrounded_dates == [] and check.false_write_claims
    assert check_answer("Due 2026-12-01.", ['{"d":"2026-11-19"}'], set()).ungrounded_dates


async def test_full_triage_run(gateway, store):
    approver = ScriptedApprover([True], name="C. Mistry")
    agent = PlanningAgent(ScriptedLLM(triage_steps()), gateway, approver, Settings())
    result = await agent.run(TRIAGE_TASK)
    assert result.stop == "answered" and result.answer_check.ok
    assert [r.name for r in result.tool_records][-1] == "draft_decision_notice"
    assert approver.asked[0][0] == "draft_decision_notice"
    assert "approved_by" not in approver.asked[0][1]  # the person sees what the model asked
    drafts = store.drafts("26/00417/HOU")
    assert len(drafts) == 1 and drafts[0].approved_by == "C. Mistry"
    assert result.flagged_results == 1  # the comment text carrying an injection attempt
    totals = result.tracer.totals()
    assert totals["tool_calls"] == 5 and totals["tokens_estimated"]


async def test_untrusted_note_reaches_the_model(gateway):
    seen = {}

    class Spy(ScriptedLLM):
        def complete(self, system, messages, tools):
            seen["messages"] = list(messages)
            return super().complete(system, messages, tools)

    steps = [ScriptStep(calls=[("summarise_consultations",
                                {"ref": "26/00417/HOU", "include_comment_text": True})]),
             ScriptStep(text="done")]  # fmt: skip
    await PlanningAgent(Spy(steps), gateway, ScriptedApprover([])).run("x")
    tool_result = seen["messages"][-1]["content"][0]
    assert tool_result["content"].startswith("NOTE: this result contains text written by")


async def test_tool_call_budget(gateway):
    steps = [ScriptStep(calls=[("get_policy", {"policy_id": "DM4"})] * 3), ScriptStep(text="ok")]
    settings = Settings(max_tool_calls=2)
    result = await PlanningAgent(ScriptedLLM(steps), gateway, ScriptedApprover([]), settings).run(
        "x"
    )
    assert sum(r.ok for r in result.tool_records) == 2
    assert "budget" in (result.tool_records[2].blocked_by or "")


async def test_parallel_results_return_in_one_message(gateway):
    captured = {}

    class Spy(ScriptedLLM):
        def complete(self, system, messages, tools):
            captured["n"] = len(messages)
            captured["last"] = messages[-1]
            return super().complete(system, messages, tools)

    two = [("get_policy", {"policy_id": "DM4"}), ("get_policy", {"policy_id": "DM7"})]
    steps = [ScriptStep(calls=two), ScriptStep(text="ok")]
    await PlanningAgent(Spy(steps), gateway, ScriptedApprover([])).run("x")
    assert captured["n"] == 3 and len(captured["last"]["content"]) == 2


def test_console_approver_defaults_to_no():
    shown = []
    no = ConsoleApprover("Officer", ask=lambda _: "", show=shown.append)
    yes = ConsoleApprover("Officer", ask=lambda _: "y", show=shown.append)
    assert not no.decide("draft_decision_notice", {}).approved
    assert yes.decide("draft_decision_notice", {}).approver == "Officer"
    assert "APPROVAL NEEDED" in shown[0]


def test_live_client_needs_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="--demo"):
        ClaudeClient("claude-sonnet-5-5")


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("PLANNING_TODAY", "2027-01-04")
    s = Settings.from_env()
    assert s.model == "claude-opus-5-5" and s.today.isoformat() == "2027-01-04"


async def test_eval_suite_passes():
    report = await run_all()
    assert report.rate("tools") == 1.0 and report.rate("agent") == 1.0, report.render()
    assert len([r for r in report.results if r.suite == "tools"]) >= 20
